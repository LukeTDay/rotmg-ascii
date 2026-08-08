from Networking.Packets.Packet import Packet

class StacksPacket(Packet):
    def __init__(self):
        self.type = "STACKS"
        # The local player's temporary base-stat stack counters (e.g. from
        # stat potions stacking), one unsigned byte each in this fixed order -
        # confirmed via realmlib (stacks-packet.ts/stacks-state.ts). RealmShark
        # has no equivalent definition.
        self.hp = 0
        self.mp = 0
        self.attack = 0
        self.defense = 0
        self.speed = 0
        self.vitality = 0
        self.wisdom = 0
        self.dexterity = 0

    def read(self, reader):
        self.hp = reader.readUnsignedByte()
        self.mp = reader.readUnsignedByte()
        self.attack = reader.readUnsignedByte()
        self.defense = reader.readUnsignedByte()
        self.speed = reader.readUnsignedByte()
        self.vitality = reader.readUnsignedByte()
        self.wisdom = reader.readUnsignedByte()
        self.dexterity = reader.readUnsignedByte()

    def write(self, writer):
        writer.writeUnsignedByte(self.hp)
        writer.writeUnsignedByte(self.mp)
        writer.writeUnsignedByte(self.attack)
        writer.writeUnsignedByte(self.defense)
        writer.writeUnsignedByte(self.speed)
        writer.writeUnsignedByte(self.vitality)
        writer.writeUnsignedByte(self.wisdom)
        writer.writeUnsignedByte(self.dexterity)
