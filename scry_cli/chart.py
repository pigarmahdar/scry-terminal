"""Pure Python ASCII & Unicode charting for terminal card price trends.

Zero external dependencies. Supports sparklines and multi-line ANSI trend curves.
"""
import math
import re

from .state import c


def render_sparkline(values: list[float]) -> str:
    """Render a compact 1-line sparkline from a series of numbers."""
    if not values:
        return ""
    ticks = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return ""
    min_v = min(clean)
    max_v = max(clean)
    span = max_v - min_v
    if span <= 1e-9:
        return ticks[3] * len(clean)
    out = []
    for v in clean:
        idx = int((v - min_v) / span * (len(ticks) - 1))
        idx = max(0, min(len(ticks) - 1, idx))
        out.append(ticks[idx])
    return "".join(out)


def render_trend_chart(
    prices: list[tuple[str, float]],
    title: str = "",
    width: int = 50,
    height: int = 6,
    currency: str = "$",
    use_color: bool = True,
) -> str:
    """Render a multi-line ASCII/Unicode trend chart with price and date axes.

    `prices` is expected to be a chronological list of `(date_str, price_float)`.
    """
    if not prices:
        return ""

    # Clean and filter valid numeric entries
    clean_series: list[tuple[str, float]] = []
    for d, p in prices:
        try:
            if p is not None:
                clean_series.append((str(d), float(p)))
        except (ValueError, TypeError):
            continue

    if not clean_series:
        return ""

    if len(clean_series) == 1:
        d, p = clean_series[0]
        return f"       1 snapshot recorded ({d}): {currency}{p:.2f}"

    dates = [d for d, _ in clean_series]
    vals = [p for _, p in clean_series]
    min_val = min(vals)
    max_val = max(vals)

    # Artificial buffer if line is completely flat
    if abs(max_val - min_val) < 1e-5:
        min_val = max(0.0, min_val * 0.95)
        max_val = max_val * 1.05 if max_val > 0 else 1.0

    first_val = vals[0]
    last_val = vals[-1]
    pct_change = ((last_val - first_val) / first_val * 100.0) if first_val > 0 else 0.0

    # ANSI styles
    c_reset = "\033[0m" if use_color else ""
    c_green = "\033[1;32m" if use_color else ""
    c_red = "\033[1;31m" if use_color else ""
    c_dim = "\033[2m" if use_color else ""
    c_title = "\033[1;33m" if use_color else ""

    trend_color = c_green if pct_change > 0 else (c_red if pct_change < 0 else "")

    # Y-axis ticks
    val_step = (max_val - min_val) / max(1, height - 1)
    y_labels = [f"{currency}{min_val + i * val_step:.2f}" for i in range(height)]
    max_label_w = max(len(lbl) for lbl in y_labels)
    y_labels = [lbl.rjust(max_label_w) for lbl in y_labels]

    # Available plot width (space for horizontal points)
    # Total width minus indent (7) + label width + 3 for " ┤ "
    left_margin = 7 + max_label_w + 3
    plot_width = max(18, min(width - left_margin, 55))

    # Resample or interpolate vals into plot_width columns
    resampled_y: list[int] = []
    n_pts = len(vals)
    for col in range(plot_width):
        src_idx = col * (n_pts - 1) / max(1, plot_width - 1)
        low_idx = int(math.floor(src_idx))
        high_idx = int(math.ceil(src_idx))
        fraction = src_idx - low_idx
        interpolated = vals[low_idx] * (1.0 - fraction) + vals[high_idx] * fraction
        row = int(round((interpolated - min_val) / (max_val - min_val) * (height - 1)))
        row = max(0, min(height - 1, row))
        resampled_y.append(row)

    # Build 2D character grid: height rows x plot_width cols
    grid = [[" " for _ in range(plot_width)] for _ in range(height)]

    for x in range(plot_width):
        curr_y = resampled_y[x]
        next_y = resampled_y[x + 1] if x < plot_width - 1 else curr_y

        if curr_y == next_y:
            grid[curr_y][x] = "─"
        elif next_y > curr_y:
            grid[curr_y][x] = "╯"
            for mid in range(curr_y + 1, next_y):
                grid[mid][x] = "│"
            grid[next_y][x] = "╭"
        else:  # next_y < curr_y
            grid[curr_y][x] = "╮"
            for mid in range(next_y + 1, curr_y):
                grid[mid][x] = "│"
            grid[next_y][x] = "╰"

    lines = []
    if title:
        lines.append(f"       {c_title}{title}{c_reset}")

    for row_idx in range(height - 1, -1, -1):
        lbl = y_labels[row_idx]
        sep = "┼" if row_idx == 0 else "┤"
        row_chars = "".join(grid[row_idx])
        colored_chars = f"{trend_color}{row_chars}{c_reset}"
        lines.append(f"       {lbl} {sep} {colored_chars}")

    # X-axis timeline markers (bottom axis)
    axis_line = " " * (7 + max_label_w) + " └" + "─" * plot_width
    lines.append(axis_line)

    # Format 3 to 4 date labels across plot_width
    date_labels_line = list(" " * (plot_width + max_label_w + 12))
    num_date_ticks = min(4, len(dates))
    if num_date_ticks > 1:
        step = (plot_width - 1) / (num_date_ticks - 1)
        date_step = (len(dates) - 1) / (num_date_ticks - 1)
        for i in range(num_date_ticks):
            col_x = int(round(i * step)) + max_label_w + 9
            d_idx = int(round(i * date_step))
            raw_d = str(dates[d_idx])
            clean_d = re.sub(r"\D", "", raw_d)
            if len(clean_d) == 8:
                lbl = f"{clean_d[4:6]}/{clean_d[6:8]}"
            else:
                lbl = raw_d[-5:]

            if i == num_date_ticks - 1:
                start_pos = col_x - len(lbl) + 1
            elif i == 0:
                start_pos = col_x
            else:
                start_pos = col_x - len(lbl) // 2

            for ch_idx, ch in enumerate(lbl):
                if 0 <= start_pos + ch_idx < len(date_labels_line):
                    date_labels_line[start_pos + ch_idx] = ch

    lines.append(f"{c_dim}{''.join(date_labels_line).rstrip()}{c_reset}")

    # Summary line
    sign = "+" if pct_change > 0 else ""
    summary = (
        f"       Low: {currency}{min_val:.2f}  •  "
        f"High: {currency}{max_val:.2f}  •  "
        f"Current: {currency}{last_val:.2f} "
        f"({trend_color}{sign}{pct_change:.1f}%{c_reset} over {len(dates)} points)"
    )
    lines.append(summary)

    return "\n".join(lines)
