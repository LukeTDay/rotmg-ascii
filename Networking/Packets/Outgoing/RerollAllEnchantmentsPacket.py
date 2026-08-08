from Networking.Packets.Packet import Packet

class RerollAllEnchantmentsPacket(Packet):
    """
    Sent to reroll an item's enchantments. The server acknowledges with an
    EnchantPacket, then publishes the resulting enchantments in stat 80 on a
    subsequent NewTickPacket.

    Layout: artifactMode:u8, equipmentSlotId:u16, artifactInventorySlot:i16,
    lockedSlotCount:u8, lockedSlotIndices:u8[count].
    """

    def __init__(self):
        self.type = "REROLLALLENCHANTMENTS"
        self.artifactMode = 0
        self.equipmentSlotId = 0
        self.artifactInventorySlot = -1
        self.lockedSlotIndices = []

    def read(self, reader):
        self.artifactMode = reader.readUnsignedByte()
        self.equipmentSlotId = reader.readUnsignedShort()
        self.artifactInventorySlot = reader.readShort()
        lockedSlotCount = reader.readUnsignedByte()
        self.lockedSlotIndices = [reader.readUnsignedByte() for _ in range(lockedSlotCount)]

    def write(self, writer):
        writer.writeUnsignedByte(self.artifactMode)
        writer.writeUnsignedShort(self.equipmentSlotId)
        writer.writeShort(self.artifactInventorySlot)
        writer.writeUnsignedByte(len(self.lockedSlotIndices))
        for idx in self.lockedSlotIndices:
            writer.writeUnsignedByte(idx)
