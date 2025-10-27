

class ParserWrapper:
    def __init__(self):
        self.user_parser = UserParser()
        self.order_parser = OrderParser()
        self.dm_parser = DMParser()


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
    def parse(self, input_data):
        pass
