import argparse
import logging
import traceback
from typing import Dict, Any, List

from sqlalchemy.exc import SQLAlchemyError


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


def check_balance(*_) -> str:
    return "Your current balance is €X.XX"


class DMParser:

    def __init__(self):
        self.parser = argparse.ArgumentParser(
            description="Information about your balance and recent orders via direct message",
            prog="DMParser",
            add_help=False,
            usage="%(prog)s options:",
        )

        self.sub_parsers = self.parser.add_subparsers()

        balance_parser = self.sub_parsers.add_parser(
            "balance",
            help="Check your current balance"
        )
        balance_parser.set_defaults(func=check_balance)

        balance_parser.add_argument(
            "--all", "-a", action="store_true", help="Show balance information for all rooms"
        )

    def parse(self, input_data: List[str]) -> str:

        try:
            args = self.parser.parse_args(input_data)
            logging.debug(f"DMParser args: {args}")
            return args.func(vars(args))

        except (SystemExit, AttributeError, argparse.ArgumentError):
            traceback.print_exc()
            self.parser.format_help()

        except SQLAlchemyError as e:
            logging.error(f"Database error: {e}")
            return "An error occurred while accessing the database."

        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            traceback.print_exc()
            return "An unexpected error occurred."




