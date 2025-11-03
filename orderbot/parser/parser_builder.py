import argparse
from typing import List, Dict
from orderbot.parser.parser_specs import CommandSpec


def build_dm_parser(
    command_specs: List[CommandSpec],
    prog: str,
    description: str,
    usage: str,
    add_help: bool = False,
) -> tuple[argparse.ArgumentParser, Dict[str, argparse.ArgumentParser]]:

    parser = argparse.ArgumentParser(
        prog=prog,
        description=description,
        usage=usage,
        add_help=add_help,
    )

    subparsers = parser.add_subparsers(dest="cmd", required=True)

    subparser_map: Dict[str, argparse.ArgumentParser] = {}

    for spec in command_specs:
        sp = subparsers.add_parser(
            spec.name,
            help=spec.help,
            description=spec.description,
        )

        sp.set_defaults(func=spec.func)

        for arg in spec.arguments:
            sp.add_argument(*arg.names, **arg.kwargs)

        subparser_map[spec.name] = sp

    return parser, subparser_map