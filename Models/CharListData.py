from typing import List

class CharListData():
    def __init__(self,
                 charID : int,
                 objectType : int,
                 isSeasonal : bool,
                 currentFame : int,
                 currentLevel : int,
                 equipmentList : List[int],
                 isInCrucible : bool) -> None:
        self.charID = charID
        self.objectType = objectType
        self.isSeasonal = isSeasonal
        self.currentFame = currentFame
        self.currentLevel = currentLevel
        self.equipmentList = equipmentList
        self.isInCrucible = isInCrucible