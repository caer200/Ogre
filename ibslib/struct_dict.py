
import os

from ase import Atoms
from pymatgen.core.structure import Structure as StructureP
from pymatgen.core.structure import Molecule

from ibslib import Structure
from ibslib.io import read,write
from ibslib.io.check import check_ext,check_format,format2extension,check_dir


class StructDict(dict):
    """
    Specifies the bahvior of a StructureDictionary which is abbreviated as 
    struct_dict throughout the code base. The StructDict currently 
    is exactly the same as a Python dictionary where each key is the struct_id
    and each value is a Structure.]

    """
    def __init__(self, directory_path="", file_format=""):
        """
        Creates StructDict for the optional input directory path.

        """
        if len(directory_path) > 0:
            if not os.path.isdir(directory_path):
                raise Exception("Path {} for ".format(directory_path)+
                        "StructDict construction was not a directory.")

            self.update(read(directory_path,file_format=file_format))
            
    
    def update(self, struct):
        """
        Behaves as a wrapper to append
        
        """
        self.append(struct, struct.struct_id)
    

    def append(self, struct, struct_id=""):
        """
        Append a structure to the the StructDict

        Arguments
        ---------
        struct: ibslib/ASE/Pymatgen
            Can be a Structure object from ibslib, ASE, or Pymatgen
        struct_id: str


        """
        struct_type = type(struct)

        ## Structure types will be handled a bit differently
        if struct_type == Structure:
            ## Modify struct_id if desired
            if len(struct_id) > 0:
                struct.struct_id = struct_id
            self[struct.struct_id] = struct
            return
        elif struct_type == Atoms:
            temp_struct = Structure.from_ase(struct)
        elif struct_type == Molecule:
            temp_struct = Structure.from_pymatgen(struct)
        elif struct_type == StructureP:
            temp_struct = Structure.from_pymatgen(struct)
        else:
            raise Exception("Object {} of type {} could not be appended "
                            .format(struct, struct_type)+
                            "to the StructDict.")
        
        ## Now handle struct_id for cases where object was not ibslib
        if len(struct_id) > 0:
            temp_struct.struct_id = struct_id
        else:
            temp_struct.get_struct_id(universal=True)

        self[temp_struct.struct_id] = temp_struct


class StructDictStream():
    """
    StructDict that behaves like a Structure Dictionary but is implemented in 
    a streaming way. This means that when it's attached to a directory of 
    structures
    
    Arguments
    ---------
    directory_path: str
        Path to the directory to connect to the StructDictStream
    file_format: str
        Default File format to save added Structures. 
    overwrite: bool
        If True, then Structures in the directory may be overwritten. 
    wq: bool
        If True, then when Structures are closed, they will be saved to the 
        directory. This used in the values and items methods. 
    
    
    """
    def __init__(self, directory_path="", file_format="json", overwrite=False,
                 wq=False):
        self.directory_path = directory_path
        self.overwrite = overwrite
        self.wq = wq
        
        ## Check file_format setting
        self.file_format = file_format
        check_format(file_format)
        ## Store extension for later use 
        self.file_ext = format2extension[file_format]
        

        ## Storage. Key is the Structure id, value is the name of the file the 
        ## strucutre ID refers to so that the file can later be referenced,
        ## opened, and read. In addition, saving ID in dictionary provides
        ## very fast lookup.
        ## self.id_dict = {"struct_id": file_name in self.directory_path}
        self.id_dict={}

        if len(directory_path) > 0:
            check_dir(directory_path)
            self.reload()
    

    def reload(self):
        """
        Reloads relevant values for file_list and id list from directory path.
        Assumes that Structure.struct_id is always equal to file_name without
        the extensions. In general, this should be correct, and in addition it 
        shouldn't cause any errors even if the assumption is incorrect.

        """
        file_list = os.listdir(self.directory_path)
        self.id_dict = {}

        ## I worry a bit that this loop may be too slow for very large 
        ## directories. Seems to work very quickly for thousands of 
        ## Structures. 
        for file_name in file_list:
            ext = check_ext(file_name)
            struct_id = file_name.replace(".{}".format(ext),"")
            self.id_dict[struct_id] = file_name

        del(file_list)
    
    def update(self, struct):
        """
        Behaves as a wrapper to __setitem__
        
        """
        self.__setitem__(struct.struct_id, struct)
        

    def __setitem__(self, key, struct):
        """
        Adds Structure file to self.directory_path using self.file_format. 
        Updates self.id_dict with relevant struct_id and file_name. 
        
        """
        if type(struct) != Structure:
            raise Exception("Cannot add object of type {}"
                            .format(type(self.file_ext ))+
                            "to StructDictStream")
        
        file_name = "{}.{}".format(struct.struct_id, 
                                   self.file_ext)
        file_path = os.path.join(self.directory_path, file_name)
        write(file_path, struct, file_format=self.file_format, 
              overwrite=self.overwrite)
        
        ## Now that the structure is written store value in self.id_dict
        self.id_dict[struct.struct_id] = file_name
        
    
    def __getitem__(self, key):
        file_name = self.id_dict[key]
        file_path = os.path.join(self.directory_path, file_name)
        s = read(file_path)
        return s

    def __iter__(self):
        return iter(self.id_dict.keys())
    
    def __len__(self):
        return len(self.id_dict)

    def __delitem__(self, key):
        del(self.id_dict[key])
    
    def has_key(self, k):
        return k in self.id_dict
    
    def keys(self):
        return self.id_dict.keys()
    
    def values(self):
        """
        Implemented using generator so only a single file is open at a time as 
        the values are iterated. This is the correct implementation for 
        streaming behavior.

        """
        s = None
        for struct_id,file_name in self.id_dict.items():
            ## Check write and quit behaviorm
            if s != None and self.wq == True:
                self.update(s)
            file_path = os.path.join(self.directory_path, file_name)
            s = read(file_path)
            if s == None:
                continue
            yield s
        ## Write last Structure
        if s != None and self.wq == True:
            self.update(s)
    
    def items(self):
        """
        Similar to values

        """
        s = None
        for struct_id,file_name in self.id_dict.items():
            ## Check write and quit behaviorm
            if s != None and self.wq == True:
                self.update(s)
            file_path = os.path.join(self.directory_path, file_name)
            s = read(file_path)
            if s == None:
                continue
            yield struct_id,s
        ## Write last Structure
        if s != None and self.wq == True:
            self.update(s)
            
            
class SDS(StructDictStream):
    """
    Shorter name for StructDictStream
    """
    
            

class StructDictMongo():
    """
    Structure Dictionary that interacts with a MongoDB while preserving 
    StructDict API.
    
    When this is constructed, it will connected the MongoDB to the entire 
    ibslib API. This means that any analysis that people will want to do using 
    Driver parallelization is plug-and-play.
    
    
    
    """
    def __init__(self):
        raise Exception("Not Implemented")
        
    



"""
All special methods for Python containers from: 
https://docs.python.org/3/reference/datamodel.html?emulating-container-types#emulating-container-types

    def __setitem__(self, key, item):
        self.__dict__[key] = item

    def __getitem__(self, key):
        return self.__dict__[key]

    def __repr__(self):
        return repr(self.__dict__)

    def __len__(self):
        return len(self.__dict__)

    def __delitem__(self, key):
        del self.__dict__[key]

    def clear(self):
        return self.__dict__.clear()

    def copy(self):
        return self.__dict__.copy()

    def has_key(self, k):
        return k in self.__dict__

    def update(self, *args, **kwargs):
        return self.__dict__.update(*args, **kwargs)

    def keys(self):
        return self.__dict__.keys()

    def values(self):
        return self.__dict__.values()

    def items(self):
        return self.__dict__.items()

    def pop(self, *args):
        return self.__dict__.pop(*args)

    def __cmp__(self, dict_):
        return self.__cmp__(self.__dict__, dict_)

    def __contains__(self, item):
        return item in self.__dict__

    def __iter__(self):
        return iter(self.__dict__)

    def __unicode__(self):
        return unicode(repr(self.__dict__))
"""