from Networking.Packets.Packet import Packet


class ApplyEnchantmentPacket(Packet):
    def __init__(self):
        self.type = "APPLYENCHANTMENT"
        self.unknown = 0
        self.enchantment_type = 0
        self.add = True
        self.enchantment_slot_id = 0

    def read(self, reader):
        self.unknown = reader.readShort()
        self.enchantment_type = reader.readShort()
        self.add = reader.readBool()
        self.enchantment_slot_id = reader.readByte()

    def write(self, writer):
        writer.writeShort(self.unknown)
        writer.writeShort(self.enchantment_type)
        writer.writeBool(self.add)
        writer.writeByte(self.enchantment_slot_id)