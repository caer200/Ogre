

import numpy as np
import spglib as spg


class UniquePlanes():
    """
    Given a ASE atoms crystal structure, finds and returns the unique planes. 
    The algorithm first finds the space group for the system. More specifically,
    it finds the Hall Number which is particularly important for monoclinic 
    systems where it's necessary to know the direction of the unique axis. Then,
    the symmetry operations of the space group are applied to miller index to 
    identify how it transfroms. If the miller index transforms to onto another,
    this these are necessarily specifying identical planes. This information is
    catalogued inside the class and a list of unique miller indices is returned. 

    You may also note, symmetry operations with translation components, 
    including centering operations, screw axis, and glide planes create
    additional degenate planes. For example, if the (100) plane is in the
    direction of a 2_1 screw, then the (100) and (200) planes are identical. 

    For a compelete list of space groups and hall numbers, please visit:
        http://pmsl.planet.sci.kobe-u.ac.jp/~seto/?page_id=37&lang=en

    Parameters
    ---------
    atoms: ase.atoms
        Crystal structure to identify unique planes
    index: int
        Maximum miller index to use in plane creation. 
    min_d: float
        Minimum interplanar spacing to use in Angstroms. As distance 
        decreases, the morphological importance decreases. 
    z_prime: float
        Number of molecules in the asymmetric unit. If the number is equal
        to 1, then (100) and (200) will necessarily be the same. However, 
        if there is more than 1 molecule in the asymmetric unit, this 
        is not generally the case. 
    symprec: float
        Precision used within spglib for space group identification. 
    verbose: bool
        True if the user would like informative print statements during
        operation. 

    """

    def __init__(self, atoms, index=1, min_d=1.0, z_prime=1,
                 symprec=1e-3, verbose=True):
        if index < 0:
            raise Exception("Index must be greater than zero.")
        if np.sum(atoms.pbc) != 3:
            raise Exception("Atoms object was not a 3D crystal structure.")

        self.atoms = atoms
        self.index = index
        self.symprec = symprec
        self.verbose = verbose

        self.all_idx = self.prep_idx()
        # Remove zero index
        self.all_idx = self.all_idx[1:, :]

        self.hall_number = self.get_hall_number(atoms, symprec=self.symprec)
        self.find_unique_planes(self.hall_number, z_prime=z_prime)
        

    def prep_idx(self):
        """
        Prepares all possible miller indices using the maximum index. 

        """
        idx_range = np.arange(-self.index, self.index+1)[::-1]
        # Sort idx_range array so the final list is sorted by magnitude
        # so that lower index, and positive index, planes are given preference
        sort_idx = np.argsort(np.abs(idx_range))
        idx_range = idx_range[sort_idx]
        return np.array(
            np.meshgrid(idx_range, idx_range, idx_range)).T.reshape(-1, 3)

    def get_cell(self, atoms=None):
        """
        Returns a cell tuple of the atoms object for use with spglib

        """
        if atoms == None:
            atoms = self.atoms
        lattice = atoms.cell.tolist()
        positions = atoms.get_scaled_positions().tolist()
        numbers = atoms.numbers.tolist()
        cell = (lattice, positions, numbers)
        return cell
    

    def get_hall_number(self, atoms=None, symprec=1e-3):
        """
        Get Hall number using spglib

        Arguments
        ---------
        atoms: ase.atoms
            Crystal structure to identify space group
        symprec: float
            Precision used for space group identification. 

        """
        if atoms == None:
            atoms = self.atoms
        
        cell = self.get_cell(atoms)
        dataset = spg.get_symmetry_dataset(cell,
                                           symprec=symprec)
        if self.verbose:
            print("Space group identified was {}"
                  .format(dataset["international"]))

        return dataset["hall_number"]
    
    
    def miller_to_real(self, miller_idx):
        """
        Convert miller indices to real space vectors to apply symmetry 
        operations in real space.
        
        Arguments
        ---------
        miller_idx: np.float64[:,3]
            Matrix of miller indices. 
        
        """
        ## Matrix is stored in row-wise fasion
        recp_lat = atoms.get_reciprocal_cell()
        ## Build reciprocal metric tensor. 
        ## This function has been validated to be correct for recp matric tensor
        recp_mt = np.dot(recp_lat, recp_lat.T)
        ## Real space vectors for the miller indices can be calculated easily
        real_space_mi = np.dot(miller_idx, recp_mt)
        return real_space_mi
    
    
    def real_to_miller(self, real_space):
        """
        Convert real space vectors into miller indices.
        
        Arguments
        ---------
        real_space: np.float64[:,3]
            Matrix of real space vectors. 
            
        """
        ## Matrix is stored in row-wise fasion
        recp_lat = atoms.get_reciprocal_cell()
        ## Build reciprocal metric tensor. 
        ## This function has been validated to be correct for recp matric tensor
        recp_mt = np.dot(recp_lat, recp_lat.T)
        ## May introduce rounding errors, but unlikely
        rounded = np.round(np.dot(np.linalg.inv(recp_mt), 
                               np.vstack(real_space).T).T)
        return rounded.astype(int)
        

    def idx_to_str(self, idx):
        """
        Turns idx array into a unique string representation for use that is
        numerically stable in a hash table. Only two decimal places after the 
        float are only ever required for miller index computations. 

        """
        return ",".join(["{:.0f}".format(x) for x in idx])
    

    def str_to_idx(self, idx_str):
        """
        Turns idx array into a unique string representation for use that is
        numerically stable in a hash table. Only two decimal places after the 
        float are only ever required for miller index computations. 

        """
        return [float(x) for x in idx_str.split(",")]
    

    def find_unique_planes(self, hall_number, z_prime=1, mt=True):
        """
        From hall number, calculates the unique planes.

        Arguments
        ---------
        hall_number: int
            Hall number of space group for unique plane identification. 
            For a compelete list of space groups and hall numbers, please visit:
            http://pmsl.planet.sci.kobe-u.ac.jp/~seto/?page_id=37&lang=en
        z_prime: float
            Number of molecules in the asymmetric unit. If the number is equal
            to 1, then (100) and (200) will necessarily be the same. However, 
            if there is more than 1 molecule in the asymmetric unit, this 
            is not generally the case. 
        mt: bool
            This is really just an argument from testing the algorithm. 
            If mt is True, then the reciprocal metric tensor is used to convert
            the miller indices into real space before applying symmetry 
            operations. This is the physically correct this to do. mt should
            always be set to True. If False, symmetry operations are applied
            to the miller indices, which is not crystallographically correct. 

        """
        dataset = spg.get_symmetry_from_database(hall_number)
        self.sym_ops = [(r, t) for r, t in zip(dataset['rotations'],
                                               dataset['translations'])]
        sym_ops = self.sym_ops

        # Dictionary to store idx that have already been used by algorithm
        # Dictonary is used for O(1) lookup time because of internal hash tabel
        self.used_idx = {}

        # For use when symmetry elements have translation components
        self.not_used_idx = {}
        self.not_used_idx.update(zip([self.idx_to_str(x) for x in self.all_idx],
                                     [x.tolist() for x in self.all_idx]))

        # List to compile unique indicies
        self.unique_idx = []
        
        miller_idx = self.all_idx
        
        if mt:
            miller_idx = self.miller_to_real(miller_idx)
        
        for idx in miller_idx:
            
            if mt:
                test = self.real_to_miller(idx[None,:])[0]
                idx_str = ",".join(["{:.0f}".format(x) for x in test])
            else:
                # str format for dictionary storage to be independent of numerical
                # precision.
                idx_str = ",".join(["{:.0f}".format(x) for x in idx])

            # First check if idx has been used before
            if self.used_idx.get(idx_str):
                continue
            else:
                # Otherise it must be a unique index
                self.unique_idx.append(idx)
                del(self.not_used_idx[idx_str])

                # Doesn't really matter what the value is
                self.used_idx[idx_str] = ". ".join([
                    "Thanks for reading the source code",
                    "Please checkout my website: ibier.io"])

            # Now apply all symmetry operations to idx and add these to dict
            for rotation, translation in sym_ops:
                transformed = np.dot(rotation, idx) + translation
                
                if mt:
                    test = self.real_to_miller(transformed[None,:])[0]
                    trans_str = ",".join(["{:.0f}".format(x) for x in test])
                else:
                    trans_str = ",".join(["{:.0f}".format(x) for x in transformed])

                # Can simply add to dictionary
                self.used_idx[trans_str] = ". ".join([
                    "Thanks for reading the source code",
                    "Please checkout my website: ibier.io"])

                if self.not_used_idx.get(trans_str):
                    print(idx_str,trans_str)
                    del(self.not_used_idx[trans_str])
        
        if mt:
            self.unique_idx = self.real_to_miller(self.unique_idx)


if __name__ == "__main__":
    from ibslib.io import read
    
    max_idx = 2
    
#    s = read("/Users/ibier/Research/Documents/Publications/Interfaces/Results/20190311_Sunny/HOJCOB/bulk.cif")
#    s = read("/Users/ibier/Research/Results/Hab_Project/FUQJIK/4_mpc/Experimental/relaxation/geometry.in")
#    s = read("/Users/ibier/Research/Documents/Publications/Interfaces/Test_Structures/GIYHUR_2mpc_spg3.json")
#    atoms = s.get_ase_atoms()
#    up = UniquePlanes(atoms, max_idx, symprec=0.1)
#    print(len(up.unique_idx))
    
    tet = read("/Users/ibier/Research/Documents/Publications/Interfaces/Results/20190311_Sunny/TETCEN/bulk.cif")
    tet_atoms = tet.get_ase_atoms()
    tet_up = UniquePlanes(tet_atoms, max_idx, symprec=0.01)
    print(len(tet_up.unique_idx))
    
#    print("-------------------")
#    tet_up.find_unique_planes(tet_up.hall_number, mt=False)
#    print(len(np.vstack(tet_up.unique_idx)))
    
#    pstruct = s.get_pymatgen_structure()
#    tet_pstruct = tet.get_pymatgen_structure()
#    
#    
#    for rot,trans in up.sym_ops:
#        print("----------------------")
#        print(trans)
#        print(rot)
        
        
#    ### Get reciprocal lattice
#    recp_lat = pstruct.lattice.reciprocal_lattice_crystallographic
#    ## Matrix is stored in row-wise fasion
#    real_matrix = pstruct.lattice.matrix
#    recp_matrix = recp_lat.matrix
#    
#    ## Build reciprocal metric tensor. 
#    ## This function has been validated to be correct for recp matric tensor
#    real_mt = np.dot(real_matrix, real_matrix.T)
#    recp_mt = np.dot(recp_matrix, recp_matrix.T)
#    
#    ## Real space vectors for the miller indices can be calculated easily
#    real_space_mi = np.dot(up.all_idx, recp_mt)
#    
#    
#    up.all_idx = real_space_mi
#    
#    up.find_unique_planes(up.hall_number)
#    
#    ## Convert back into reciprocal space
#    temp = np.round(np.dot(np.linalg.inv(recp_mt), np.vstack(up.unique_idx).T).T)
#    
#    
#    print(len(up.unique_idx))
    
    
    
    
