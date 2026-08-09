from Networking.Packets.Packet import Packet

class AccountListPacket(Packet):
    """Server-pushed account-id lists, selected by `accountListId` (confirmed
    against realmlib's captured-packet tests): 0 = the lock list, 1 = the
    ignore list. `lockAction` says how to apply `accountIds` to that list:
    -1 = replace it wholesale (snapshot, sent e.g. right after login),
    0 = remove these ids, 1 = add these ids. `accountIds` are account ids,
    not display names - match against a GameObject's ACCOUNTIDSTAT, not
    NAMESTAT.
    """

    def __init__(self):
        self.type = "ACCOUNTLIST"
        self.accountListId = 0
        self.accountIds = []
        self.lockAction = 0

    def read(self, reader):
        self.accountListId = reader.readInt32()
        accountIdsNum = reader.readShort()
        for i in range(accountIdsNum):
            self.accountIds.append(reader.readStr())
        self.lockAction = reader.readInt32()

    def write(self, writer):
        writer.writeInt32(self.accountListId)
        writer.writeShort(len(self.accountIds))
        for i in range(len(self.accountIds)):
            writer.writeStr(self.accountIds[i])
        writer.writeInt32(self.lockAction)
