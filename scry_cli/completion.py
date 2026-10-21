"""Shell completion scripts for scry (bash, zsh, fish)."""
import sys

_BASH_COMPLETION = """_scry_completions() {
    local cur prev words cword
    _init_completion 2>/dev/null || {
        cur="${COMP_WORDS[COMP_CWORD]}"
        prev="${COMP_WORDS[COMP_CWORD-1]}"
    }

    local commands="name text type color cmc keyword oracle fuzzy random search price image deck update reindex doctor completion version help"
    local flags="--limit --commander --legal --exact --sort --size --out --border --format --pretty --json --jsonl --csv --tsv --no-db --version -v --help -h"

    if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "$flags" -- "$cur") )
        return 0
    fi

    case "$prev" in
        --legal)
            COMPREPLY=( $(compgen -W "commander modern standard legacy vintage pauper pioneer brawl" -- "$cur") )
            return 0
            ;;
        --sort)
            COMPREPLY=( $(compgen -W "name cmc price" -- "$cur") )
            return 0
            ;;
        --format)
            COMPREPLY=( $(compgen -W "pretty json jsonl csv tsv" -- "$cur") )
            return 0
            ;;
        --size)
            COMPREPLY=( $(compgen -W "small normal large png" -- "$cur") )
            return 0
            ;;
        completion)
            COMPREPLY=( $(compgen -W "bash zsh fish" -- "$cur") )
            return 0
            ;;
        deck)
            COMPREPLY=( $(compgen -f -- "$cur") )
            return 0
            ;;
    esac

    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
        return 0
    fi
}

complete -F _scry_completions scry scryfall
"""

_ZSH_COMPLETION = """#compdef scry scryfall

_scry() {
    local -a commands
    commands=(
        'name:Search by card name'
        'text:Search by oracle text'
        'type:Search by type line'
        'color:Search by colour identity'
        'cmc:Search by mana value'
        'keyword:Search by keyword ability'
        'oracle:Canonical card text only'
        'fuzzy:Fuzzy name search'
        'random:Get a random card'
        'search:General search across name + text + type'
        'price:Search by name showing market prices'
        'image:Download PNG image of a card'
        'deck:Analyze a decklist'
        'update:Update Oracle cache from Scryfall'
        'reindex:Rebuild local search index'
        'doctor:Report index health and staleness'
        'completion:Generate shell completion script'
        'version:Show version'
        'help:Show help message'
    )

    _arguments -C \\
        '--limit[Max results]:limit:' \\
        '--commander[Commander colour identity (e.g. WUBRG)]:' \\
        '--legal[Only cards legal in format]:format:(commander modern standard legacy vintage pauper pioneer brawl)' \\
        '--exact[Exact name match only]' \\
        '--sort[Sort field]:sort:(name cmc price)' \\
        '--size[Image size]:size:(small normal large png)' \\
        '--out[Output directory]:dir:_files -/' \\
        '--border[Border colour]:border:(black silver)' \\
        '--format[Output format]:format:(pretty json jsonl csv tsv)' \\
        '--pretty[Force human-styled output]' \\
        '--json[JSON output]' \\
        '--jsonl[JSONL output]' \\
        '--csv[CSV output]' \\
        '--tsv[TSV output]' \\
        '--no-db[Bypass search index]' \\
        '(-v --version)'{-v,--version}'[Show version]' \\
        '(-h --help)'{-h,--help}'[Show help]' \\
        '1: :->command' \\
        '*:: :->args'

    case $state in
        command)
            _describe -t commands 'scry command' commands
            ;;
        args)
            case $words[1] in
                deck)
                    _files
                    ;;
                completion)
                    _values 'shell' bash zsh fish
                    ;;
            esac
            ;;
    esac
}

compdef _scry scry scryfall 2>/dev/null || true
"""

_FISH_COMPLETION = """complete -c scry -c scryfall -f

# Commands
complete -c scry -c scryfall -n "__fish_use_subcommand" -a name -d "Search by card name"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a text -d "Search by oracle text"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a type -d "Search by type line"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a color -d "Search by colour identity"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a cmc -d "Search by mana value"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a keyword -d "Search by keyword ability"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a oracle -d "Canonical card text only"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a fuzzy -d "Fuzzy name search"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a random -d "Get a random card"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a search -d "General search across name + text + type"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a price -d "Search by name showing market prices"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a image -d "Download PNG image of a card"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a deck -d "Analyze a decklist"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a update -d "Update Oracle cache from Scryfall"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a reindex -d "Rebuild local search index"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a doctor -d "Report index health and staleness"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a completion -d "Generate shell completion script"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a version -d "Show version"
complete -c scry -c scryfall -n "__fish_use_subcommand" -a help -d "Show help message"

# Flags
complete -c scry -c scryfall -l limit -d "Max results" -r
complete -c scry -c scryfall -l commander -d "Commander colour identity" -r
complete -c scry -c scryfall -l legal -d "Format legality" -x -a "commander modern standard legacy vintage pauper pioneer brawl"
complete -c scry -c scryfall -l exact -d "Exact name match only"
complete -c scry -c scryfall -l sort -d "Sort field" -x -a "name cmc price"
complete -c scry -c scryfall -l size -d "Image size" -x -a "small normal large png"
complete -c scry -c scryfall -l out -d "Output directory" -r
complete -c scry -c scryfall -l border -d "Border colour" -x -a "black silver"
complete -c scry -c scryfall -l format -d "Output format" -x -a "pretty json jsonl csv tsv"
complete -c scry -c scryfall -l pretty -d "Force human-styled output"
complete -c scry -c scryfall -l json -d "JSON output"
complete -c scry -c scryfall -l jsonl -d "JSONL output"
complete -c scry -c scryfall -l csv -d "CSV output"
complete -c scry -c scryfall -l tsv -d "TSV output"
complete -c scry -c scryfall -l no-db -d "Bypass search index"
complete -c scry -c scryfall -s v -l version -d "Show version"
complete -c scry -c scryfall -s h -l help -d "Show help message"

# Completion subcommand arguments
complete -c scry -c scryfall -n "__fish_seen_subcommand_from completion" -a "bash zsh fish"
"""

SHELL_SCRIPTS = {
    "bash": _BASH_COMPLETION,
    "zsh": _ZSH_COMPLETION,
    "fish": _FISH_COMPLETION,
}


def handle_completion(shell: str) -> None:
    """Emit the completion script for the requested shell."""
    from .project import emit_single
    from .state import c, machine_mode

    shell_name = (shell or "").strip().lower()
    script = SHELL_SCRIPTS.get(shell_name)
    if not script:
        if machine_mode():
            emit_single(
                {
                    "error": "invalid_shell",
                    "shell": shell_name,
                    "valid_shells": sorted(SHELL_SCRIPTS.keys()),
                }
            )
        else:
            print("\n  " + c("✗ Invalid or missing shell.", "1;31"))
            print("  Usage: scry completion <bash|zsh|fish>\n")
        sys.exit(1)

    sys.stdout.write(script)
