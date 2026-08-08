from Networking.Packets.Packet import Packet


class UnlockEnchantmentSlotPacket(Packet):
    def __init__(self):
        self.type = "UNLOCKENCHANTMENTSLOT"
        self.enchantment_id = 0
        self.slot_id = 0

    def read(self,reader):
        self.enchantment_id = reader.readShort()
        self.slot_id = reader.readByte()
    
    def write(self,writer): 
        writer.writeShort(self.enchantment_id)
        writer.writeByte(self.slot_id)
