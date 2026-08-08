from Networking.Packets.Packet import Packet

class TutorialStateChangedPacket(Packet):
    def __init__(self):
        self.type = "TUTORIALSTATECHANGED"

    def read(self, reader):
        pass

    def write(self, writer):
        pass
