#!/usr/bin/env python3
"""Spike test for terminal trend chart and sparkline rendering.

Validates:
1. Dynamic terminal sizing & scaling
2. Multi-line Unicode trend charts with rising/falling/flat curves
3. ANSI color formatting
4. Sparklines
"""

from datetime import datetime, timedelta
import math


def render_sparkline(values: list[float]) -> str:
    """Render a compact 1-line sparkline from a series of numbers."""
    if not values:
        return ""
    ticks = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
    min_v = min(values)
    max_v = max(values)
    span = max_v - min_v
    if span <= 1e-9:
        return ticks[3] * len(values)
    out = []
    for v in values:
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
    """Render a multi-line ASCII/Unicode trend chart with price and date axes."""
    if not prices:
        return "  (No price history available)"

    # Extract clean floats
    clean_series: list[tuple[str, float]] = []
    for d, p in prices:
        try:
            clean_series.append((d, float(p)))
        except (ValueError, TypeError):
            continue

    if not clean_series:
        return "  (No valid price history)"

    if len(clean_series) == 1:
        d, p = clean_series[0]
        return f"  Single record on {d}: {currency}{p:.2f}"

    dates = [d for d, _ in clean_series]
    vals = [p for _, p in clean_series]
    min_val = min(vals)
    max_val = max(vals)

    # If min == max, give it artificial breathing room
    if abs(max_val - min_val) < 1e-5:
        min_val = max(0.0, min_val * 0.95)
        max_val = max_val * 1.05 if max_val > 0 else 1.0

    # Colors
    c_reset = "\033[0m" if use_color else ""
    c_bold = "\033[1m" if use_color else ""
    c_green = "\033[1;32m" if use_color else ""
    c_red = "\033[1;31m" if use_color else ""
    c_dim = "\033[2m" if use_color else ""
    c_title = "\033[1;33m" if use_color else ""

    first_val = vals[0]
    last_val = vals[-1]
    pct_change = ((last_val - first_val) / first_val * 100.0) if first_val > 0 else 0.0
    trend_color = c_green if pct_change > 0 else (c_red if pct_change < 0 else "")

    # Calculate y-axis label width
    val_step = (max_val - min_val) / (height - 1)
    y_labels = [f"{currency}{min_val + i * val_step:.2f}" for i in range(height)]
    max_label_w = max(len(lbl) for lbl in y_labels)
    y_labels = [lbl.rjust(max_label_w) for lbl in y_labels]

    # Available plot width (space for horizontal points)
    # Total width minus: 2 indent + label width + 3 for " ┤ " or " ┼─"
    left_margin = 2 + max_label_w + 3
    plot_width = max(15, min(width - left_margin, 60))

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

    # Build the 2D character grid: height rows x plot_width cols
    # Row 0 is bottom (min_val), Row height-1 is top (max_val)
    grid = [[" " for _ in range(plot_width)] for _ in range(height)]

    for x in range(plot_width):
        curr_y = resampled_y[x]
        prev_y = resampled_y[x - 1] if x > 0 else curr_y
        next_y = resampled_y[x + 1] if x < plot_width - 1 else curr_y

        if curr_y == next_y:
            grid[curr_y][x] = "─"
        elif next_y > curr_y:
            # Rising toward right: bottom is ╯, verticals are │, top is ╭
            grid[curr_y][x] = "╯"
            for mid in range(curr_y + 1, next_y):
                grid[mid][x] = "│"
            grid[next_y][x] = "╭"
        else:  # next_y < curr_y
            # Falling toward right: top is ╮, verticals are │, bottom is ╰
            grid[curr_y][x] = "╮"
            for mid in range(next_y + 1, curr_y):
                grid[mid][x] = "│"
            grid[next_y][x] = "╰"

    # Assemble lines
    lines = []
    if title:
        lines.append(f"  {c_title}{title}{c_reset}")

    for row_idx in range(height - 1, -1, -1):
        lbl = y_labels[row_idx]
        sep = "┼" if row_idx == 0 else "┤"
        row_chars = "".join(grid[row_idx])
        colored_chars = f"{trend_color}{row_chars}{c_reset}"
        lines.append(f"  {lbl} {sep} {colored_chars}")

    # X-axis timeline markers (bottom axis)
    axis_line = " " * (max_label_w + 3) + "└" + "─" * plot_width
    lines.append(axis_line)

    # Format 3 to 4 date labels across plot_width
    date_labels_line = list(" " * (plot_width + max_label_w + 10))
    num_date_ticks = min(4, len(dates))
    if num_date_ticks > 1:
        step = (plot_width - 1) / (num_date_ticks - 1)
        date_step = (len(dates) - 1) / (num_date_ticks - 1)
        for i in range(num_date_ticks):
            col_x = int(round(i * step)) + max_label_w + 4
            d_idx = int(round(i * date_step))
            raw_d = dates[d_idx]
            # Try to format as MM/DD
            try:
                clean_d = raw_d.replace("-", "")
                if len(clean_d) == 8:
                    lbl = f"{clean_d[4:6]}/{clean_d[6:8]}"
                else:
                    lbl = raw_d[-5:]
            except Exception:
                lbl = raw_d[:5]

            # Right align the last tick, center middle ticks, left align first tick
            if i == num_date_ticks - 1:
                start_pos = col_x - len(lbl) + 1
            elif i == 0:
                start_pos = col_x
            else:
                start_pos = col_x - len(lbl) // 2

            for ch_idx, ch in enumerate(lbl):
                if 0 <= start_pos + ch_idx < len(date_labels_line):
                    date_labels_line[start_pos + ch_idx] = ch

    lines.append(f"{c_dim}{''.join(date_labels_line)}{c_reset}")

    # Summary line
    sign = "+" if pct_change > 0 else ""
    summary = (
        f"  Low: {currency}{min_val:.2f}  •  "
        f"High: {currency}{max_val:.2f}  •  "
        f"Current: {currency}{last_val:.2f} "
        f"({trend_color}{sign}{pct_change:.1f}%{c_reset} {len(dates)}d)"
    )
    lines.append(summary)

    return "\n".join(lines)


def main():
    print("Testing Sparkline:")
    vals = [1.02, 1.05, 1.08, 1.15, 1.12, 1.25, 1.35, 1.45]
    print(f"  Prices: {vals}")
    print(f"  Sparkline: [{render_sparkline(vals)}]")

    print("\n" + "=" * 60 + "\n")
    print("Testing Multi-line Trend Chart (Rising):")

    # Generate 30 days of mock rising prices
    start_date = datetime(2026, 9, 28)
    prices = []
    cur = 0.92
    for i in range(30):
        d_str = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
        if i in (5, 12, 20, 26):
            cur += 0.10
        elif i % 4 == 0:
            cur += 0.02
        prices.append((d_str, round(cur, 2)))

    chart = render_trend_chart(
        prices,
        title="Sol Ring (Commander Masters) — 30-Day USD Trend",
        width=55,
        height=6,
        currency="$",
    )
    print(chart)

    print("\n" + "=" * 60 + "\n")
    print("Testing Multi-line Trend Chart (Falling):")
    cur = 45.00
    falling_prices = []
    for i in range(30):
        d_str = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
        if i in (4, 10, 18):
            cur -= 3.50
        elif i % 3 == 0:
            cur -= 0.50
        falling_prices.append((d_str, round(cur, 2)))

    chart_fall = render_trend_chart(
        falling_prices,
        title="Sheoldred, the Apocalypse — 30-Day USD Trend",
        width=55,
        height=6,
        currency="$",
    )
    print(chart_fall)


if __name__ == "__main__":
    main()
