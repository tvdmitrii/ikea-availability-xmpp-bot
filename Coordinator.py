import asyncio
import json
import subprocess
import sched, time
import threading

from slixmpp import JID

from xmpp_message_bot import MessageIn, MessageOut, EchoBot


class Bot:
    def __init__(self, coordinator, name=""):
        self.name = name
        self.coordinator = coordinator

    def processMessage(self, msg: MessageIn):
        return None


class IkeaBot(Bot):
    def __init__(self, coordinator, delay, name=""):
        super().__init__(coordinator, name)
        self.command = ["npx", "ikea-availability-checker", "stock", "--store=560", "--reporter", "json", "40431564",
                        "90341151"]
        self.delay = delay
        self.subscribers = [JID("JID_SUB1"), JID("JID_SUB2")]
        self.coordinator.scheduler.enter(self.delay, 1, self.checkAvailability)

    def processMessage(self, msg: MessageIn):
        response = ""
        if msg.body == "status":
            products = self.executeCommand()
            for product in products:
                response = response + "Item: " + product["productId"] + "\n"
                response = response + "Current stock: " + str(product["availability"]["stock"]) + "\n"
                response = response + "Store: " + product["store"]["name"] + "\n"
                response = response + "Restock Date: " + product["availability"]["restockDate"][:10] + "\n"

                forecasts = product["availability"]["forecast"]
                response = response + "Forecast:\n"
            for forecast in forecasts:
                response = response + "-----\n"
                response = response + "\tProbability: " + forecast["probability"] + "\n"
                response = response + "\tDate: " + forecast["date"][:10] + "\n"
                response = response + "\tStock: " + str(forecast["stock"]) + "\n"
            response = response + "\n---------\n\n"

        msg_out = MessageOut(mto=msg.mfrom, mtype=msg.mtype, body=response)
        self.coordinator.sendMessage(msg_out)

    def executeCommand(self):
        # result = subprocess.run(["cat", "stock.json"], capture_output=True, text=True)
        result = subprocess.run(self.command, capture_output=True, text=True)
        result = "[\n" + result.stdout[2:-3] + "]"
        products = json.loads(result)

        return products

    def checkAvailability(self):
        products = self.executeCommand()

        for product in products:
            item = product["productId"]
            stock = product["availability"]["stock"]
            if stock != 0:
                body = "Friheten is available! Item: " + str(item) + ", stock: " + str(stock) + ". Try ordering " \
                                                                                                "online or call +1-414-766-0560. Extension 1412."
                for subscriber in self.subscribers:
                    self.coordinator.sendMessage(MessageOut(subscriber, "chat", body))

        self.coordinator.scheduler.enter(self.delay, 1, self.checkAvailability)
        return None


class Coordinator:
    def __init__(self, jid, password):
        self.bots = []
        self.xmpp = EchoBot(jid, password)
        self.xmpp.initialize()
        self.xmpp.setMessageReceivedCallback(self.processMessage)

        self.scheduler = sched.scheduler(time.time, time.sleep)

    def start(self):
        th = threading.Thread(target=self.wrapper)
        th.start()
        self.xmpp.connect()
        self.xmpp.process()
        self.xmpp.loop.stop()
        th.join()

    def wrapper(self):
        self.scheduler.run(blocking=True)

    def addBot(self, bot: Bot):
        self.bots.append(bot)

    def processMessage(self, msg: MessageIn):
        msg.body = msg.body.lower()
        parts = msg.body.split(" ")
        for bot in self.bots:
            if parts[0] == bot.name:
                msg.body = msg.body[len(parts[0]) + 1:]
                bot.processMessage(msg)

    def sendMessage(self, msg: MessageOut):
        self.xmpp.send_message(msg)


if __name__ == '__main__':
    jid = "JID_BOT"
    password = "YOUR_PASSWORD"

    coord = Coordinator(jid, password)
    ikeabot = IkeaBot(coord, 60, "ikea")
    coord.addBot(ikeabot)
    coord.start()
