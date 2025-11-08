import argparse
import logging
import traceback
from typing import List

from orderbot.db.db_classes import Participant
from orderbot.parser.parser_builder import build_dm_parser
from orderbot.parser.parser_specs import CommandSpec, ArgSpec

from sqlalchemy.exc import SQLAlchemyError

def _strip_usage(help_text: str) -> str:
    lines = help_text.splitlines()
    if lines and lines[0].lstrip().startswith("usage:"):
        idx = 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        return "\n".join(lines[idx:])
    return help_text

class ParserWrapper:
    def __init__(self, db_session, room):
        self.user_parser = UserParser()
        self.order_parser = OrderParser()
        self.dm_parser = DMParser()
        self.db_session = db_session
        self.room = room
        self.order = None


    def parse_msg(self, input_data, direct):
        if direct:
            return self.dm_parser.parse(input_data)

        if "order" in input_data:
            return self.order_parser.parse(input_data)

        if "user" in input_data:
            return self.user_parser.parse(input_data)

        return "Wrong input data"




class UserParser:
    def parse(self, input_data):
        pass

class OrderParser:
    def parse(self, input_data):
        pass





class DMParser:
    def __init__(self, db_session):
        self.db_session = db_session
        specs = [
            CommandSpec(
                name="balance",
                func=self.check_balance,
                help="Show your current balance.",
                description=(
                    "Show your current balance."
                ),
                arguments=[
                    ArgSpec(
                        names=("--all", "-a"),
                        kwargs={"action": "store_true", "help": "Show the full balance history."},
                    ),
                ],
            ),



        ]


        self.parser, self.subparser_map = build_dm_parser(
            specs,
            prog="DMParser",
            description="Information about your balance and recent orders via direct message",
            usage="DMParser <command> [options]",
            add_help=False,
        )

    def check_balance(self, namespace) -> str:
        user = namespace.user_id
        show_all = getattr(namespace, "all", False)
        try:
            participant = (
                self.db_session.query(Participant)
                .filter(Participant.matrix_address == user)
                .first()
            )
            if not participant:
                return "User not found in the database."
            balance = participant.user_total
            if show_all:
                return f"Full balance history for {user} is not implemented yet."
            else:
                return f"Your current balance is: {balance} cents."

        except SQLAlchemyError as e:
            logging.error(f"Database error: {e}\n{traceback.format_exc()}")
            return "An error occurred while accessing the database."


    def parse(self, input_data: List[str], user_id) -> str:
        try:
            if input_data and input_data[-1] in ("-h", "--help"):
                if len(input_data) >= 2 and input_data[0] in self.subparser_map:
                    return _strip_usage(self.subparser_map[input_data[0]].format_help())
                return _strip_usage(self.parser.format_help())

            args = self.parser.parse_args(input_data)
            setattr(args, "user_id", user_id)
            if hasattr(args, "func"):
                return args.func(args)
            return _strip_usage(self.parser.format_help())

        except SystemExit:
            if input_data and input_data[0] in self.subparser_map:
                return _strip_usage(self.subparser_map[input_data[0]].format_help())
            return _strip_usage(self.parser.format_help())
        except argparse.ArgumentError as e:
            logging.error(f"Argument parsing error: {e}")
            return f"Argument parsing error: {e}"
        except Exception as e:
            logging.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
            return f"An unexpected error occurred: {e}"





