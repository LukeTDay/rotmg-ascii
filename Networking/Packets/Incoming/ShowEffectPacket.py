from Networking.Packets.Packet import Packet
from Data.WorldPosData import *

# effectType (realmlib VisualEffect enum; 34 is an unassigned gap):
# 0 UNKNOWN, 1 HEAL, 2 TELEPORT, 3 STREAM, 4 THROW, 5 NOVA, 6 POISON, 7 LINE,
# 8 BURST, 9 FLOW, 10 RING, 11 LIGHTNING, 12 COLLAPSE, 13 CONEBLAST, 14 JITTER,
# 15 FLASH, 16 THROW_PROJECTILE, 17 SHOCKER, 18 SHOCKEE, 19 RISING_FURY,
# 20 NOVA_NO_AOE, 21 INSPIRED, 22 HOLY_BEAM, 23 CIRCLE_TELEGRAPH, 24 CHAOS_BEAM,
# 25 TELEPORT_MONSTER, 26 METEOR, 27 GILDED_BUFF, 28 JADE_BUFF, 29 CHAOS_BUFF,
# 30 THUNDER_BUFF, 31 STATUS_FLASH, 32 FIRE_ORB_BUFF, 33 OVERLAY,
# 35 SUMMONER_EFFECT, 36 KENSEI_DASH_TRAIL, 37 KENSEI_CHANNEL_DASH, 38 ATTACK,
# 39 AOE, 40 SHOCK_BLAST.
# THROW (4) and THROW_PROJECTILE (16) both precede a real AOE landing
# (confirmed live capture, 2026-08-14 - Tundra Yeti's Yeti Bomb telegraphs
# via THROW_PROJECTILE, not THROW) - see Models/AoeStore.py. THROW_PROJECTILE
# reuses the `color` field for the flying visual projectile's own objectType
# (e.g. Yeti Boulder=0x768), not a real color - see
# AoeStore.spawnTelegraphIfKnown's colorHint handling.
class ShowEffectPacket(Packet):
    def __init__(self):
        self.type = "SHOWEFFECT"
        self.effectType = 0
        self.ignore = 0
        self.targetObjectId = 0
        self.pos1 = WorldPosData()
        self.pos2 = WorldPosData()
        self.color = 0
        self.duration = 0
        self.extra = False
        self.unknownByte = 0

    def read(self, reader):
        self.effectType = reader.readUnsignedByte()
        self.ignore = reader.readUnsignedByte()#Better way to do this?
            
        if self.ignore&64:
            self.targetObjectId = reader.readCompressedInt()
        else:
            self.targetObjectId = 0
            
        if self.ignore&2:
            self.pos1.x = reader.readFloat()
        else:
            self.pos1.x = 0
            
        if self.ignore&4:
            self.pos1.y = reader.readFloat()
        else:
            self.pos1.y = 0
            
        if self.ignore&8:
            self.pos2.x = reader.readFloat()
        else:
            self.pos2.x = 0
            
        if self.ignore&16:
            self.pos2.y = reader.readFloat()
        else:
            self.pos2.y = 0
            
        if self.ignore&1:
            self.color = reader.readInt32()
        else:
            self.color = 0
            
        if self.ignore&32:
            self.duration = reader.readFloat()
        else:
            self.duration = 0

        if reader.bytesAvailable():
            self.extra = True
            self.unknownByte = reader.readByte()

    def write(self, writer):
        writer.writeUnsignedByte(self.effectType)
        writer.writeUnsignedByte(self.ignore)

        if self.ignore&64:
            writer.writeCompressedInt(self.targetObjectId)
            
        if self.ignore&2:
            writer.writeFloat(self.pos1.x)
            
        if self.ignore&4:
            writer.writeFloat(self.pos1.y)
            
        if self.ignore&8:
            writer.writeFloat(self.pos2.x)
            
        if self.ignore&16:
            writer.writeFloat(self.pos2.y)
            
        if self.ignore&1:
            writer.writeInt32(self.color)
            
        if self.ignore&32:
            writer.writeFloat(self.duration)

        if self.extra:
            writer.writeByte(self.unknownByte)
