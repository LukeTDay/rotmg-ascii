from Networking.Packets.Packet import Packet
from Data.WorldPosData import *

class PlayerShootPacket(Packet):
    def __init__(self):
        self.type = "PLAYERSHOOT"
        self.time = 0
        self.shotId = 0
        self.containerType = 0
        self.bulletId = 0#-1 if the weapon doesn't have a bullet type
        self.shotPos = WorldPosData()
        self.angle = 0
        # Unsigned, not a bool - real client sends 0..24 here (burst
        # index/count for multi-projectile weapons like Longbow). This app
        # doesn't send real burst weapons yet (see CLAUDE.local.md), so
        # always 0 for now.
        self.burstId = 0
        # Two independent bytes, not one int16 (was merged as unknownShort=
        # -256 here, which happened to byte-match by coincidence: -256's
        # big-endian encoding is exactly [0xff, 0x00] = these two fields'
        # real values below - confirmed against rotmg_mitm_py's PlayerShoot,
        # citing realmlib's 2026-08-01 protocol audit, 278,452 captured
        # bodies): a signed byte (only 0xff/-1 observed for players) and
        # PlayerShootSource (Primary=0, Ability=1). This app only ever fires
        # the primary weapon, so always -1/0.
        self.unknownShotByte = -1
        self.shootSource = 0
        self.pos = WorldPosData()

    def write(self, writer):
        writer.writeInt32(self.time)
        writer.writeShort(self.shotId)
        writer.writeUnsignedShort(self.containerType)
        writer.writeByte(self.bulletId)
        self.shotPos.write(writer)
        writer.writeFloat(self.angle)
        writer.writeUnsignedByte(self.burstId)
        writer.writeByte(self.unknownShotByte)
        writer.writeUnsignedByte(self.shootSource)
        self.pos.write(writer)

    def read(self, reader):
        self.time = reader.readInt32()
        self.shotId = reader.readShort()
        self.containerType = reader.readUnsignedShort()
        self.bulletId = reader.readByte()
        self.shotPos.read(reader)
        self.angle = reader.readFloat()
        self.burstId = reader.readUnsignedByte()
        self.unknownShotByte = reader.readByte()
        self.shootSource = reader.readUnsignedByte()
        self.pos.read(reader)
