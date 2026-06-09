"""
Entry point: python -m jarvis
Also exposed as the 'jarvis' console script via setup.cfg.
"""

import sys
from .config.manager import ConfigManager
from .openrouter.client import OpenRouterClient
from .agent import JarvisAgent
from .repl.loop import run_repl


def main() -> None:
    try:
        config_manager = ConfigManager()
        client = OpenRouterClient()
    except EnvironmentError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        sys.exit(1)

    agent = JarvisAgent(client, config_manager)
    run_repl(agent, config_manager)


if __name__ == "__main__":
    main()
