from Networking.Packets.Packet import Packet


class UnlockEnchantmentPacket(Packet):
    def __init__(self):
        self.type = "UNLOCKENCHANTMENT"
        self.unknown = 0
        self.enchantment_type = 0

    def read(self,reader):
        self.unknown = reader.readShort()
        self.enchantment_type = reader.readShort()
    
    def write(self,writer): 
        writer.writeShort(self.unknown)
        writer.writeShort(self.enchantment_type)
