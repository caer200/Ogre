# -*- coding: UTF-8 -*-

import math
import pymatgen as mg
from ase.utils import gcd, basestring
from ase.build import bulk
from copy import deepcopy
from numpy.linalg import norm, solve
# from pymatgen.analysis.graphs import MoleculeGraph, StructureGraph
# from pymatgen.core.structure import Molecule
from pymatgen.io.vasp.inputs import Poscar
from ase import io
import networkx.algorithms.isomorphism as iso
import numpy as np
import networkx as nx
from pymatgen.core.lattice import Lattice
from pymatgen.core.sites import PeriodicSite
# used for deciding which atoms are bonded
from pymatgen.analysis.local_env import JmolNN
import os
import sys
import time
from functools import wraps
from collections import Counter


def from_ASE_to_pymatgen(working_dir, images):
    """
    change ASE structure to pymatgen structure
    """
    file_name = working_dir + "/temp.POSCAR.vasp"
    io.write(file_name, images,parallel=False)
    modify_poscar(file_name)
    slab = mg.Structure.from_file(file_name)
    os.remove(file_name)
    return slab

def modify_poscar(file):
    """
    Change the file to compliant POSCAR.
    """
    index = 0
    prev_file = open(file, 'r')
    new_file = open(file+'.new', 'w')
    for line in prev_file:
        if index == 0:
            tmp = line
            new_file.write('slab\n')
        elif index == 5:
            new_file.write(tmp)
            new_file.write(line)
        else:
            new_file.write(line)
        index = index+1
    os.rename(file+'.new', file)


def surface(lattice, indices, layers, tol=1e-10, termination=0):
    """Create surface from a given lattice and Miller indices.

    lattice: Atoms object or str
        Bulk lattice structure of alloy or pure metal.  Note that the
        unit-cell must be the conventional cell - not the primitive cell.
        One can also give the chemical symbol as a string, in which case the
        correct bulk lattice will be generated automatically.
    indices: sequence of three int
        Surface normal in Miller indices (h,k,l).
    layers: int
        Number of equivalent layers of the slab.
    termination: int
        The termination "number" for your crystal. The same value will not
        produce the same termination for different symetrically identical
        bulk structures, but changing this value allows your to explore all
        the possible terminations for the bulk structure you provide it.
        note: this code is not well tested
    """

    indices = np.asarray(indices)

    if indices.shape != (3,) or not indices.any() or indices.dtype != int:
        raise ValueError('%s is an invalid surface type' % indices)

    if isinstance(lattice, basestring):
        lattice = bulk(lattice, cubic=True)

    h, k, l = indices
    h0, k0, l0 = (indices == 0)

    if termination != 0:  # changing termination
        import warnings
        warnings.warn('Work on changing terminations is currently in '
                      'progress.  Code may not behave as expected.')
        lattice1 = deepcopy(lattice)
        cell = lattice1.get_cell()
        pt = [0, 0, 0]
        millers = list(indices)
        for index, item in enumerate(millers):
            if item == 0:
                millers[index] = 10 ** 9  # make zeros large numbers
            elif pt == [0, 0, 0]:  # for numerical stability
                pt = list(cell[index] / float(item) /
                          np.linalg.norm(cell[index]))
        h1, k1, l1 = millers
        N = np.array(cell[0] / h1 + cell[1] / k1 + cell[2] / l1)
        n = N / np.linalg.norm(N)  # making a unit vector normal to cut plane
        d = [np.round(np.dot(n, (a - pt)), 4)
             for a in lattice.get_scaled_positions()]
        d = set(d)
        d = sorted(list(d))
        d = [0] + d  # distances of atoms from cut plane
        displacement = (h * cell[0] + k * cell[1] +
                        l * cell[2]) * d[termination]
        lattice1.positions += displacement
        lattice = lattice1

    if h0 and k0 or h0 and l0 or k0 and l0:  # if two indices are zero
        if not h0:
            c1, c2, c3 = [(0, 1, 0), (0, 0, 1), (1, 0, 0)]
        if not k0:
            c1, c2, c3 = [(0, 0, 1), (1, 0, 0), (0, 1, 0)]
        if not l0:
            c1, c2, c3 = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
    else:
        p, q = ext_gcd(k, l)
        a1, a2, a3 = lattice.cell

        # constants describing the dot product of basis c1 and c2:
        # dot(c1,c2) = k1+i*k2, i in Z
        k1 = np.dot(p * (k * a1 - h * a2) + q * (l * a1 - h * a3),
                    l * a2 - k * a3)
        k2 = np.dot(l * (k * a1 - h * a2) - k * (l * a1 - h * a3),
                    l * a2 - k * a3)

        if abs(k2) > tol:
            i = -int(round(k1 / k2))  # i corresponding to the optimal basis
            p, q = p + i * l, q - i * k

        a, b = ext_gcd(p * k + q * l, h)

        c1 = (p * k + q * l, -p * h, -q * h)
        c2 = np.array((0, l, -k)) // abs(gcd(l, k))
        c3 = (b, a * p, a * q)

    surf = build(lattice, np.array([c1, c2, c3]), layers, tol)
    return surf


def ext_gcd(a, b):
    """
    Extended Euclidean Algorithm. Find the result for ax + by = gcd(a, b).

    Parameters
    ----------
    a: int
    b: int
    """
    if b == 0:
        return 1, 0
    elif a % b == 0:
        return 0, 1
    else:
        x, y = ext_gcd(b, a % b)
        return y, x - y * (a // b)


def build(lattice, basis, layers, tol):
    """
    Transform the structure to original surface based on basis.

    Parameters
    ----------
    basis: 3 * 3 matrix, [[a, b, c], ...]
        the basis vectors of the target surfaces.
    lattice: Atoms object or str
        Bulk lattice structure of alloy or pure metal.  Note that the
        unit-cell must be the conventional cell - not the primitive cell.
        One can also give the chemical symbol as a string, in which case the
        correct bulk lattice will be generated automatically.
    layers: int
        Number of equivalent layers of the slab.
    """
    surf = lattice.copy()
    scaled = solve(basis.T, surf.get_scaled_positions().T).T
    scaled -= np.floor(scaled + tol)
    surf.set_scaled_positions(scaled)
    surf.set_cell(np.dot(basis, surf.cell), scale_atoms=True)
    surf *= (1, 1, layers)
    return surf


def modify_cell(structure):
    """
    This is the final step of a molecular reconstruction step, and would
    align z direction to be perpendicular to the surface

    Parameters
    ---------
    structure: Atoms object or str
        In this structure, the z direction might not be perpendicular to the
        target surface.
    """
    slab = structure.copy()
    a1, a2, a3 = slab.cell
    slab.set_cell([a1, a2,
                   np.cross(a1, a2) * np.dot(a3, np.cross(a1, a2)) /
                   norm(np.cross(a1, a2)) ** 2])

    # Change unit cell to have the x-axis parallel with a surface vector
    # and z perpendicular to the surface:
    a1, a2, a3 = slab.cell
    slab.set_cell([(norm(a1), 0, 0),
                   (np.dot(a1, a2) / norm(a1),
                    np.sqrt(norm(a2) ** 2 - (np.dot(a1, a2) / norm(a1)) ** 2), 0),
                   (0, 0, norm(a3))],
                  scale_atoms=True)
    slab.pbc = (True, True, False)

    scaled = slab.get_scaled_positions()
    scaled[:, :2] %= 1
    slab.set_scaled_positions(scaled)
    return slab


def handle_with_molecules(slab_move, delta, down=True):
    """
    Move some very tiny fragments of broken molecule to the other side. This is
    a preparation step for the move_method, which could minimize the limitations.

    Parameters
    ----------
    slab_move: Atoms structure
        slab_move is the original surfaces that is generated by ase library.
    delta: list of double, [delta_x, delta_y, delta_z]
        Add or subtract the delta (cart_coords) to the tiny broken molecules to
        initially repair parts of molecules.
    down: bool
         True: Add a delta to the tiny broken molecules that are located at the bottom,
         False: subtract a delta to the tiny broken molecules that are located at the top.
    """
    slab_sg = StructureGraph.with_local_env_strategy(slab_move, JmolNN())
    slab_supercell_sg = slab_sg * (3, 3, 1)
    slab_sg_graph = nx.Graph(slab_supercell_sg.graph)
    all_super_subgraphs = list(nx.connected_component_subgraphs
                               (slab_sg_graph))
    super_subgraphs = []
    for subgraph in all_super_subgraphs:
        intersects_boundary = any([d['to_jimage'] != (0, 0, 0)
                                   for u, v, d in subgraph.edges(data=True)])
        if not intersects_boundary:
            super_subgraphs.append(subgraph)
    for subgraph in super_subgraphs:
        for n in subgraph:
            subgraph.add_node(n,
                              specie=str(slab_supercell_sg.structure[n].specie))
    molecules = []
    for subgraph in super_subgraphs:
        coords = [slab_supercell_sg.structure[n].coords
                  for n in subgraph.nodes()]
        # get the frac_cood of every atom for every molecules
        coord_z_list = [slab_move.lattice.get_fractional_coords(
            coord)[-1] for coord in coords]
        if down is True:
            temp = [coord_z < 0.5 for coord_z in coord_z_list]
        else:
            temp = [coord_z > 0.5 for coord_z in coord_z_list]
        if not all(temp) or len(coords) > 6:
            continue
        species = [slab_supercell_sg.structure[n].specie
                   for n in subgraph.nodes()]
        molecule = mg.Molecule(species=species, coords=coords)
        molecules.append(molecule)
    # molecules are the list of molecules that need to be moved
    move_list = []
    move_sites = reduced_sites(molecules, slab_move)
    for move_site in move_sites:
        for i, atom in enumerate(slab_move):
            if atom.is_periodic_image(move_site):
                move_list.append(i)
                break
    coords_move = slab_move.cart_coords
    species_move = slab_move.species
    slab_move.remove_sites(move_list)
    for i in move_list:
        if down is True:
            new_coord = np.array(coords_move[i]) + np.array(delta)
        else:
            new_coord = np.array(coords_move[i]) - np.array(delta)
        slab_move.append(species_move[i], new_coord, coords_are_cartesian=True)
    return slab_move


def Find_Broken_Molecules(slab, sg, species_intact, coords_intact, unique_bulk_subgraphs):
    """
    Use molecular identification method to find those molecules in the surface
    that are different from that in the bulk.

    Parameters
    ----------
    slab: Atoms structure
        The surface that is generated by ase library and might have broken molecules.
    sg: list of Molecules
        Unique Molecules in bulk Structure.
    species_intact: list, ['specie_1', 'specie_2', ...]
        A list of atomic species of intact molecules.
    coords_intact: list, [[coord_1_1, coord_1_2, coord_1_3], ...]
        A list of atomic cart_coords of intact molecules.
    unique_bulk_subgraphs: list of graphs
        A list of intact molecules' graphs. Note that every graph is this list
        is unique
    """
    slab_sg = StructureGraph.with_local_env_strategy(slab, JmolNN())

    # enlarge the cell to a (3 * 3 * 1) super_cell
    slab_supercell_sg = slab_sg * (3, 3, 1)
    different_subgraphs_in_slab, slab_molecules = \
        get_slab_different_subgraphs(slab_supercell_sg, unique_bulk_subgraphs)
    slab_molecules = double_screen(slab_molecules, sg)

    # the molecules in slab_original would be the template
    #print("The number of molecules that need to be fixed : " +
    #      str(len(slab_molecules)))
    # slab_molecules are the molecules that are broken and need to be fixed

    delete_sites = reduced_sites(slab_molecules, slab)

    # delete_list is the list of broken atoms
    delete_list = []

    for delete_site in delete_sites:
        for i, atom in enumerate(slab):
            if atom.is_periodic_image(delete_site):
                delete_list.append(i)
                break
    species_all = slab.species
    coords_all = slab.cart_coords
    for i, atom in enumerate(slab):
        temp = [i == delete for delete in delete_list]
        if not any(temp):
            species_intact.append(species_all[i])
            coords_intact.append(coords_all[i])

    delete_list = []
    # remove intact molecules in the slab for convenience
    #print("Delete all atoms!")
    for i, atom in enumerate(slab):
        delete_list.append(i)
    slab.remove_sites(delete_list)

    sites = []
    for slab_molecule in slab_molecules:
        for curr_site in slab_molecule:
            curr_site = mg.PeriodicSite(curr_site.specie,
                                        curr_site.coords,
                                        slab.lattice,
                                        coords_are_cartesian=True)
            tmp = [curr_site.is_periodic_image(site) for site in sites]
            if not any(tmp):
                sites.append(curr_site)
    for site in sites:
        # add the broken molecules into the system
        slab.append(species=site.specie, coords=site.coords,
                    coords_are_cartesian=True)
    return slab


def get_broken_molecules(self, bulk_subgraphs, use_weights=False):
    # compare each molecule in slab to each molecule in the bulk,
    # get rid of isomorohic, molecules store the brokens
    """
    Retrieve broken_subgraphs as molecules

    Will return nonunique molecules, duplicates
    present in the crystal (a duplicate defined as an
    isomorphic subgraph).

    Returns:
    -------
    : list of nonunique broken Molecules in Structure
    """

    # creating a supercell is an easy way to extract
    # molecules (and not, e.g., layers of a 2D crystal)
    # without adding extra logic
    supercell_sg = self*(3, 3, 1)

    # make undirected to find connected subgraphs
    supercell_sg.graph = nx.Graph(supercell_sg.graph)

    # find subgraphs
    all_subgraphs = list(nx.connected_component_subgraphs(supercell_sg.graph))

    # discount subgraphs that lie across *supercell* boundaries
    # these will subgraphs representing crystals
    molecule_subgraphs = []
    for subgraph in all_subgraphs:
        intersects_boundary = any([d['to_jimage'] != (0, 0, 0)
                                   for u, v, d in subgraph.edges(data=True)])
        if not intersects_boundary:
            molecule_subgraphs.append(subgraph)

    # add specie names to graph to be able to test for isomorphism
    for subgraph in molecule_subgraphs:
        for n in subgraph:
            subgraph.add_node(n, specie=str(supercell_sg.structure[n].specie))

    # now define how we test for isomorphism
    def node_match(n1, n2):
        return n1['specie'] == n2['specie']

    def edge_match(e1, e2):
        if use_weights:
            return e1['weight'] == e2['weight']
        else:
            return True
    nm = iso.categorical_node_match("specie", "ERROR")
    # remove complete molecules in subgraphs
    different_subgraphs = []

    start = time.time()
    for subgraph in molecule_subgraphs:
        already_present = [nx.is_isomorphic(subgraph, g,
                                            node_match=nm)
                           for g in bulk_subgraphs]
        if not any(already_present):
            different_subgraphs.append(subgraph)

    # get Molecule objects for each subgraph
    molecules = []
    for subgraph in different_subgraphs:

        coords = [supercell_sg.structure[n].coords for n
                  in subgraph.nodes()]
        species = [supercell_sg.structure[n].specie for n
                   in subgraph.nodes()]

        molecule = Molecule(species, coords)

        # shift so origin is at center of mass
        #molecule = molecule.get_centered_molecule()

        molecules.append(molecule)

    return molecules

    # now define how we test for isomorphism


def node_match(n1, n2):
    """the strategy for node matching in is_isomorphic.
    Parameters
    ------
    n1, n2 : node

    Returns:
    -------
    True of false : bool
        based on whether the species of two nodes are the same.
    """
    return n1['specie'] == n2['specie']


def get_bulk_molecules(self, use_weights=False):
    # get rid of the repetitve molecule in bulk, only left with unique molecule######
    """
    Retrieve subgraphs as molecules, useful for extracting
    molecules from periodic crystals.

    Will only return unique molecules, not any duplicates
    present in the crystal (a duplicate defined as an
    isomorphic subgraph).

    Parameters:
    ------
    use_weights: (bool) If True, only treat subgraphs
        as isomorphic if edges have the same weights. Typically,
        this means molecules will need to have the same bond
        lengths to be defined as duplicates, otherwise bond
        lengths can differ. This is a fairly robust approach,
        but will treat e.g. enantiomers as being duplicates.

    Returns:
    -------
    list of unique Molecules in Structure
    """

    # creating a supercell is an easy way to extract
    # molecules (and not, e.g., layers of a 2D crystal)
    # without adding extra logic
    # enlarge the structureGraph object to a supercell
    supercell_sg = self*(3, 3, 1)

    # make undirected to find connected subgraphs
    # create networkx undirected graph object to
    supercell_sg.graph = nx.Graph(supercell_sg.graph)
    # store the input graph

    # find subgraphs
    all_subgraphs = list(nx.connected_component_subgraphs(
        supercell_sg.graph))
    # add specie names to graph to be able to test for isomorphism
    for subgraph in all_subgraphs:
        for n in subgraph:
            subgraph.add_node(n, specie=str(supercell_sg.structure[n].specie))

    # now define how we test for isomorphism
    def node_match(n1, n2):
        return n1['specie'] == n2['specie']

    def edge_match(e1, e2):
        if use_weights:
            return e1['weight'] == e2['weight']
        else:
            return True
    nm = iso.categorical_node_match("specie", "ERROR")
    # prune duplicate subgraphs
    unique_subgraphs = []
    for subgraph in all_subgraphs:

        already_present = [nx.is_isomorphic(subgraph, g,
                                            node_match=node_match,
                                            edge_match=edge_match)
                           for g in unique_subgraphs]

        if not any(already_present):
            unique_subgraphs.append(subgraph)

    # get Molecule objects for each subgraph
    molecules = []
    for subgraph in unique_subgraphs:

        coords = [supercell_sg.structure[n].coords for n
                  in subgraph.nodes()]
        species = [supercell_sg.structure[n].specie for n
                   in subgraph.nodes()]

        molecule = Molecule(species, coords)
        molecules.append(molecule)

    return molecules, unique_subgraphs
#################convert to undirected mx.graph and then determine if isomorphic###############


def isomorphic_to(self, other):
    """
    Checks if the graphs of two MoleculeGraphs are isomorphic to one
    another. In order to prevent problems with misdirected edges, both
    graphs are converted into undirected nx.Graph objects.

    Parameters:
    ---------- 
    other: MoleculeGraph object to be compared.
    Returns:
    -------
    bool
    """
    if self.molecule.composition != other.molecule.composition:
        return False
    else:
        self_undir = self.graph.to_undirected()
        other_undir = other.graph.to_undirected()
        nm = iso.categorical_node_match("specie", "ERROR")
        isomorphic = nx.is_isomorphic(self_undir, other_undir, node_match=nm)
        return isomorphic


def reduced_sites(molecules, slab):
    """
    Find atoms that appear again due to the periodicity.

    Parameters:
    -----------
    molecules: List[molecule].
        All molecules that might be within or out of the slab boundary.
    slab: ASE structure.
        Slab structure.

    Returns:
    --------
    sites: List[atom].
    """
    sites = []
    for molecule in molecules:
        for curr_site in molecule:
            curr_site = PeriodicSite(
                curr_site.specie, curr_site.coords, slab.lattice, coords_are_cartesian=True)
            tmp = [curr_site.is_periodic_image(site) for site in sites]
            if not any(tmp):
                sites.append(curr_site)
    return sites


def is_isomorphic(molecule1, molecule2):
    """
    Determin whether two molecules are the same.
    
    Parameters:
    -----------
    molecule1 and molecule2.

    Returns:
    --------
    bool.
    """
    return isomorphic_to(MoleculeGraph.with_local_env_strategy(molecule1, JmolNN()), MoleculeGraph.with_local_env_strategy(molecule2, JmolNN()))


def double_screen(slab_molecules, bulk_molecules):
    """
    Double check with bulk if there is any molecule already present in bulk
    """    
    delete_list = []
    for bulk_molecule in bulk_molecules:
        for i, slab_molecule in enumerate(slab_molecules):
            if is_isomorphic(bulk_molecule, slab_molecule):
                delete_list.append(i)
    tmp = [x for i, x in enumerate(slab_molecules) if i not in delete_list]
    return tmp


def print_run_time(func):
    """
    One wrapper that output the run_time of a funtion.
    """
    @wraps(func)
    def wrapper(*args, **kw):
        local_time = time.time()
        func(*args, **kw)
        print('Current Function [%s] run time is %.2fs' %
              (func.__name__, time.time() - local_time))
    return wrapper


def updatePOSCAR(output_file):
    """This function is used to correct the output file (POSCAR) of ase.

    Parameters:
    ----------
    output_file : str
        The file of surface written by the write function of ase.

    Returns:
    -------
    file : str
        The file that is corrected.
    """
    with open(output_file, 'r') as original_file:
        lines = original_file.readlines()
        line1 = lines[0]
        lines.insert(5, "  " + line1)
    with open(output_file, 'w') as final_file_1:
        for i in range(len(lines)):
            final_file_1.writelines(lines[i])
    structure = mg.Structure.from_file(output_file)
    lattice = Lattice(structure.lattice.matrix)
    frac_coords = lattice.get_fractional_coords(structure.cart_coords)
    for i in range(frac_coords.shape[0]):
        for j in range(frac_coords.shape[1]):
            if abs(frac_coords[i][j] - 1) < 1e-5:
                frac_coords[i][j] = 1
            if abs(frac_coords[i][j] - 0) < 1e-5:
                frac_coords[i][j] = 0
    with open(output_file, 'r') as final_file_2:
        lines = final_file_2.readlines()
        lines[7] = 'Direct' + '\n'
        for i in range(np.array(frac_coords).shape[0]):
            lines[8 + i] = "    " + str(np.array(frac_coords)[i, :][0]) + ' ' + str(np.array(frac_coords)[i, :][1]) +\
                           ' ' + str(np.array(frac_coords)[i, :][2]) + '\n'
    with open(output_file, 'w') as final_file:
        for i in range(len(lines)):
            final_file.writelines(lines[i])


def edge_match(e1, e2):
    """the strategy for edge matching in is_isomorphic.
    Parameters:
    ----------
    e1, e2 : edge).

    Returns:
    -------
    True or false : bool
        based on whether the length of bonds are the same or close to each other.
    """
    return abs(e1['weight'] - e2['weight']) / e2['weight'] < 1e-5


def get_bulk_subgraphs(bulk_structure_sg):
    """
    Get all subgraphs of molecules that within or crosses the boundary of
    original bulk.

    Parameters:
    -----------
    bulk_structure_sg: StructureGraph.
        The structure graph of bulk with local env strategy.

    Returns:
    --------
    super_graphs : List[graph].
        Represent the subgraphs of molecules that within or crosses the
        boundary of original bulk. 
    molecules : List[molecule].
        Molecules that are correlated to the subgraphs.
    """
    bulk_super_structure_sg_graph = nx.Graph(bulk_structure_sg.graph)
    all_super_subgraphs = list(nx.connected_component_subgraphs
                               (bulk_super_structure_sg_graph))
    super_subgraphs = []
    for subgraph in all_super_subgraphs:
        in_boundary = any([d['to_jimage'] == (0, 0, 0)
                           for u, v, d in subgraph.edges(data=True)])
        if in_boundary:
            super_subgraphs.append(subgraph)
    for subgraph in super_subgraphs:
        for n in subgraph:
            subgraph.add_node(n,
                              specie=str(bulk_structure_sg.structure[n].specie))
    for subgraph in super_subgraphs:
        if len(subgraph) == 1 and "H" in [str(bulk_structure_sg.structure[n].specie) for n in subgraph.nodes()]:
            super_subgraphs.remove(subgraph)
            continue
    molecules = []
    for subgraph in super_subgraphs:
        coords = [bulk_structure_sg.structure[n].coords
                  for n in subgraph.nodes()]
        species = [bulk_structure_sg.structure[n].specie
                   for n in subgraph.nodes()]
        molecule = mg.Molecule(species=species, coords=coords)
        molecules.append(molecule)
    return super_subgraphs, molecules


def get_bulk_subgraphs_v2(bulk_structure_sg):
    """
    Get all subgraphs of molecules that within or crosses the boundary of
    original bulk.

    Parameters:
    -----------
    bulk_structure_sg: StructureGraph.
        The structure graph of bulk with local env strategy.

    Returns:
    --------
    super_graphs : List[graph].
        Represent the subgraphs of molecules that within or crosses the
        boundary of original bulk. 
    molecules : List[molecule].
        Molecules that are correlated to the subgraphs.
    """
    bulk_super_structure_sg_graph = nx.Graph(bulk_structure_sg.graph)
    all_super_subgraphs = list(nx.connected_component_subgraphs
                               (bulk_super_structure_sg_graph))
    for subgraph in all_super_subgraphs:
        for n in subgraph:
            subgraph.add_node(n,
                              specie=str(bulk_structure_sg.structure[n].specie))
    molecules = []
    for subgraph in all_super_subgraphs:
        coords = [bulk_structure_sg.structure[n].coords
                  for n in subgraph.nodes()]
        species = [bulk_structure_sg.structure[n].specie
                   for n in subgraph.nodes()]
        molecule = mg.Molecule(species=species, coords=coords)
        molecules.append(molecule)
    return all_super_subgraphs, molecules


def get_bulk_subgraphs_v3(slab_first, bulk_structure_sg):
    """
    Get all subgraphs of molecules that within or crosses the boundary of
    original bulk and generate HashGraph to modify atoms' positions.

    Parameters:
    -----------
    slab_first: pymatgen structure.
        Original slab structure that cleaved by ASE
    bulk_structure_sg: StructureGraph.
        The structure graph of bulk with local env strategy.

    Returns:
    --------
    delta_cart: List[float].
        c_difference between two adajacent layers.
    super_graphs : List[graph].
        Represent the subgraphs of molecules that within or crosses the
        boundary of original bulk. 
    molecules : List[molecule].
        Molecules that are correlated to the subgraphs.
    """
    bulk_super_structure_sg_graph = nx.Graph(bulk_structure_sg.graph)
    all_super_subgraphs = list(nx.connected_component_subgraphs
                               (bulk_super_structure_sg_graph))
    for subgraph in all_super_subgraphs:
        for n in subgraph:
            subgraph.add_node(n,
                              specie=str(bulk_structure_sg.structure[n].specie))
    frac_coods = [0] * len(bulk_structure_sg.structure)
    initial_index = -100
    molecules = []
    for subgraph in all_super_subgraphs:
        HashGraph = {}
        for u, v, d in subgraph.edges(data=True):
            change_z = list(d['to_jimage'])[-1]
            if change_z != 0:
                change_z = 1 if slab_first.lattice.get_fractional_coords(bulk_structure_sg.structure[u].coords)[-1] > slab_first.lattice.get_fractional_coords(bulk_structure_sg.structure[v].coords)[-1] else -1
            try:
                HashGraph[str(u)].append([str(v), change_z])
            except KeyError:
                HashGraph[str(u)] = [initial_index, [str(v), change_z]]
            try:
                HashGraph[str(v)].append([str(u), -change_z])
            except KeyError:
                HashGraph[str(v)] = [initial_index, [str(u), -change_z]]
        first_node = list(HashGraph.keys())[0]
        count = 1
        HashGraph[first_node][0] = 0
        Pending_node = [first_node]
        Pending_node_2 = []
        while(count < len(list(HashGraph.keys()))):
            for node in Pending_node:
                for value in HashGraph[node][1: ]:
                    if HashGraph[value[0]][0] == initial_index:
                        count += 1
                        HashGraph[value[0]][0] = HashGraph[node][0] + value[1]
                        Pending_node_2.append(value[0])
            Pending_node = deepcopy(Pending_node_2)
            Pending_node_2 = []
        # min_z = min([value[0] for value in HashGraph.values()])
        min_z = int(Counter([value[0] for value in HashGraph.values()]).most_common(1)[0][0])
        delta = np.array(slab_first.lattice.matrix[-1])
        for key in HashGraph.keys():
            HashGraph[key][0] -= min_z

        coords = [bulk_structure_sg.structure[n].coords + delta * HashGraph[str(n)][0]
                  for n in subgraph.nodes()]
        species = [bulk_structure_sg.structure[n].specie
                   for n in subgraph.nodes()]
        molecule = mg.Molecule(species=species, coords=coords)
        molecules.append(molecule)
    return delta, all_super_subgraphs, molecules


def get_bulk_subgraphs_unique(bulk_structure_sg):
    """
    get unique subgraphs of bulk based on graph algorithm.
    This function would only return unique molecules and its graphs,
    but not any duplicates present in the crystal.
    (A duplicate defined as an isomorphic crystals.

    Parameters:
    -----------
    bulk_structure_sg : nx.SturctureGraph class,
        this one is actually the supercell one that is equal to(3, 3, 3) * unit cell.

    Returns:
    --------
    unique_super_graphs : (list) [graph, ...],
        represent the unique subgraphs in the supercell and expecially
        in the boundary of supercell.
    molecules : (list) [molecule, ...],
        represent the molecules that are correlated to the unque subgraphs.
    """
    bulk_super_structure_sg_graph = nx.Graph(bulk_structure_sg.graph)
    all_super_subgraphs = list(nx.connected_component_subgraphs
                               (bulk_super_structure_sg_graph))
    super_subgraphs = []
    for subgraph in all_super_subgraphs:
        intersects_boundary = any([d['to_jimage'] != (0, 0, 0)
                                   for u, v, d in subgraph.edges(data=True)])
        if not intersects_boundary:
            super_subgraphs.append(subgraph)
    for subgraph in super_subgraphs:
        for n in subgraph:
            subgraph.add_node(n,
                              specie=str(bulk_structure_sg.structure[n].specie))
    unique_super_subgraphs = []
    for subgraph in super_subgraphs:
        if len(subgraph) == 1 and "H" in [str(bulk_structure_sg.structure[n].specie) for n in subgraph.nodes()]:
            continue
        already_present = [nx.is_isomorphic(subgraph, g,
                                            node_match=node_match,
                                            edge_match=edge_match)
                           for g in unique_super_subgraphs]
        if not any(already_present):
            unique_super_subgraphs.append(subgraph)
    molecules = []
    for subgraph in unique_super_subgraphs:
        coords = [bulk_structure_sg.structure[n].coords
                  for n in subgraph.nodes()]
        species = [bulk_structure_sg.structure[n].specie
                   for n in subgraph.nodes()]
        molecule = mg.Molecule(species=species, coords=coords)
        molecules.append(molecule)
    return unique_super_subgraphs, molecules


def get_slab_different_subgraphs(slab_supercell_sg, unique_super_bulk_subgraphs):
    """this function is used to find all the subgraphs in slab that
        are different from those in bulk.
    Parameters:
    ----------
    slab_supercell_sg : nx.StructureGraph,
        the graph of the whole slabs.
        Note: In order to thoughtoutly describe the graph,
        the slab_supercell_sg = (3, 3, 1) * slab_sg
    unique_super_bulk_subgraphs : list.

    Returns:
    -------
    different_subgraphs : list
        [different_subgraph, ...], which is the list of subgraphs that
        are different from those in bulk. In this function,
        we would only find the different subgraphs based on its species.
    slab_molecules : list
        [slab_molecule, ...], slab_molecule is the mg.Molecule of diffenert_subgraphs.
    """
    slab_supercell_sg_graph = nx.Graph(slab_supercell_sg.graph)
    all_subgraphs = list(nx.connected_component_subgraphs
                         (slab_supercell_sg_graph))
    molecule_subgraphs = []
    for subgraph in all_subgraphs:
        intersets_boundary = any([d['to_jimage'] != (0, 0, 0)
                                  for u, v, d in subgraph.edges(data=True)])
        if not intersets_boundary:
            molecule_subgraphs.append(subgraph)

    #print("molecule_subgraphs : ", len(molecule_subgraphs))
    for subgraph in molecule_subgraphs:
        for n in subgraph:
            subgraph.add_node(n, specie=str(
                slab_supercell_sg.structure[n].specie))

    nm = iso.categorical_node_match("specie", "ERROR")
    different_subgraphs = []
    for subgraph in molecule_subgraphs:
        already_present = [nx.is_isomorphic(subgraph, g,
                                            node_match=nm)
                           for g in unique_super_bulk_subgraphs]
        if not any(already_present):
            different_subgraphs.append(subgraph)

    slab_molecules = []
    for subgraph in different_subgraphs:
        coords = [slab_supercell_sg.structure[n].coords
                  for n in subgraph.nodes()]
        species = [slab_supercell_sg.structure[n].specie
                   for n in subgraph.nodes()]
        molecule = mg.Molecule(species=species, coords=coords)
        slab_molecules.append(molecule)
    return different_subgraphs, slab_molecules


def belong_to(species1, species2):
    """
    Determine whether species1 are totally included by species2.
    """
    if len(species1) > len(species2):
        return False
    i = 0
    species_1 = species1[:]
    species_2 = species2[:]
    while i < len(species_1):
        find = False
        for j in range(len(species_2)):
            if species_1[i] == species_2[j]:
                del species_1[i]
                find = True
                del species_2[j]
                break
        if find is False:
            return False
    return True


def length_belong_to(weights1, weights2):
    """
    Determine whether weights1 are totally included by weights2
    weights are the list [weight, weight, ...] of one node
    """
    if len(weights1) > len(weights2):
        return False
    i = 0
    weights_1 = weights1[:]
    weights_2 = weights2[:]
    while i < len(weights_1):
        find = False
        for j in range(len(weights_2)):
            if abs((weights_1[i] - weights_2[j]) / weights_2[j]) < 1e-5:
                del weights_1[i]
                find = True
                del weights_2[j]
                break
        if find is False:
            return False
    return True


def weights_all_belong_to(all_weight1, all_weight2, species1, species2):
    """
    Determine whether one graph is totally included by another graph by
    comparing species and weights.
    """
    if len(all_weight1) > len(all_weight2):
        return False
    i = 0
    account = 0
    total = len(all_weight1)
    all_weight_1 = all_weight1[:]
    all_weight_2 = all_weight2[:]
    species_1 = species1[:]
    species_2 = species2[:]
    while i < len(all_weight_1):
        find = False
        for j in range(len(all_weight_2)):
            if length_belong_to(all_weight_1[i], all_weight_2[j]) and species_1[i] == species_2[j]:
                del all_weight_1[i]
                del species_1[i]
                del species_2[j]
                account += 1
                del all_weight_2[j]
                find = True
                break
        if not find:
            i += 1
    if account >= 2.0 / 3.0 * total:
        return True
    return False


def brokenMolecules_and_corresspoundingIntactMolecules(new_different_subgraphs,
                                                       unique_super_subgraphs):
    """
    NOT used in current reconstruction method!!!

    Determine the intact molecules that each molecule (broken or intact) belongs to by
    compcomparing the species and weights of broken molecules and intact
    molecules.

    Parameters:
    -----------
    new_different_subgraphs: List[subgraph].
        Subgraphs of all molecules.
    unique_super_subgraphs: List[subgraph].
        Subgraphs of all bulk's unique molecules. 

    Returns:
    --------
    qualified_subgraphs: List[subgraph].
        List of subgraph of molecules in the raw slab.
    unique_super_subgraphs: List[subgraph].
        List of subgraph of corresspounding intact molecules. The length of
        qualified_unique_subgraphs should be the same as the length of
        qualified_subgraphs.
    """
    qualified_subgraphs = []
    qualified_unique_subgraphs = []
    # account = 1
    #print("trying to find the connection between broken molecules "
    #      "and intact molecules")
    for subgraph in new_different_subgraphs:
        subgraph_species = []
        weights_all = []
        for n, nbrs in subgraph.adjacency():
            subgraph_species.append(subgraph.node[n]['specie'])
            weights = []
            for nbr, eattr in nbrs.items():
                weights.append(eattr['weight'])
            weights_all.append(weights)
        find = False
        for unique_subgraph in unique_super_subgraphs:
            unique_subgraph_species = []
            unique_weights_all = []
            for n, nbrs in unique_subgraph.adjacency():
                unique_subgraph_species.append(
                    unique_subgraph.node[n]['specie'])
                weights = []
                for nbr, eattr in nbrs.items():
                    weights.append(eattr['weight'])
                unique_weights_all.append(weights)
            if not belong_to(subgraph_species, unique_subgraph_species):
                continue
            else:
                if not weights_all_belong_to(weights_all, unique_weights_all,
                                             subgraph_species,
                                             unique_subgraph_species):
                    continue
                else:
                    find = True
                    qualified_subgraphs.append(subgraph)
                    qualified_unique_subgraphs.append(unique_subgraph)
                    break
        if find is False:
            print("can't find the qualified subgraphs")
            sys.exit()
    return qualified_subgraphs, qualified_unique_subgraphs


def fix_broken_molecules(qualified_subgraphs,
                         qualified_unique_subgraphs,
                         bulk_super_structure_sg,
                         slab_supercell_sg,
                         slab, c_frac_min, fixed_c_negative=False):
    """
    NOT used in the current reconstruction method!!!

    Fix broken molecules based on graph theory. After determine the affiliation
    between all molecules in raw slabs and intact molecules in the original
    bulk, this function would replace those broken molecules with intact
    molecules.

    Parameters:
    -----------
    qualified_subgraphs: List[subgraph].
        List of subgraphs of all molecules in the raw molecules.
    qualified_unique_subgraphs: List[subgraph].
        Each element in the list is the subgraph of corresspounding intact
        molecule of "qualified_subgraphs" in the previous list. 
    bulk_super_structure_sg: StructureGraph.
        Structure Graph of supercell (3 x 3 x 3) of original bulk.
    slab_supercell_sg: StructureGraph.
        Structure Graph of supercell (3 x 3 x 3) of raw slab.
    slab: ASE structure.
        Raw slab after ASE cleaving.
    c_frac_min: float.
        Fractional coordinate of the lowest atom in raw slabs in c direction.
    fixed_c_negative: bool
        Fix the broken molecules in the lower side or not? Default option is
        False.

    Returns:
    --------
    slab: pymatgen structure.
        Slab after reconstruction.
    """
    molecules_new = []
    #print("trying to fix the broken molecules...")
    for i in range(len(qualified_subgraphs)):
        qualified_subgraphs_species = []
        qualified_subgraphs_nodes_neibs = []
        qualified_subgraphs_all_weights = []
        nodes_qualified_subgraphs = []
        for n, nbrs in qualified_subgraphs[i].adjacency():
            nodes_qualified_subgraphs.append(n)
            neibs = []
            weights = []
            qualified_subgraphs_species.append(
                qualified_subgraphs[i].node[n]['specie'])
            for nbr, eattr in nbrs.items():
                neibs.append(nbr)
                weights.append(eattr['weight'])
            qualified_subgraphs_nodes_neibs.append(neibs)
            qualified_subgraphs_all_weights.append(weights)
        qualified_unique_subgraphs_species = []
        qualified_unique_subgraphs_nodes_neibs = []
        qualified_unique_subgraphs_all_weights = []
        nodes_qualified_unique_subgraphs = []
        for n, nbrs in qualified_unique_subgraphs[i].adjacency():
            nodes_qualified_unique_subgraphs.append(n)
            neibs = []
            weights = []
            qualified_unique_subgraphs_species.append(
                qualified_unique_subgraphs[i].node[n]['specie'])
            for nbr, eattr in nbrs.items():
                neibs.append(nbr)
                weights.append(eattr['weight'])
            qualified_unique_subgraphs_all_weights.append(weights)
            qualified_unique_subgraphs_nodes_neibs.append(neibs)
        node1 = []
        node2 = []
        account = 0
        for t in range(len(qualified_subgraphs_species)):
            account = 0
            for k in range(len(qualified_unique_subgraphs_species)):
                account = 0
                if qualified_subgraphs_species[t] == qualified_unique_subgraphs_species[k] \
                        and length_belong_to(qualified_subgraphs_all_weights[t],
                                             qualified_unique_subgraphs_all_weights[k]) \
                        and len(qualified_subgraphs_all_weights[t]) == 3:
                    node1 = [nodes_qualified_subgraphs[t]]
                    node2 = [nodes_qualified_unique_subgraphs[k]]
                    account = 0
                    for a_index, a_weight in enumerate(qualified_subgraphs_all_weights[t]):
                        for index, weight in enumerate(qualified_unique_subgraphs_all_weights[k]):
                            has1 = qualified_subgraphs_nodes_neibs[t][a_index] in node1
                            has2 = qualified_unique_subgraphs_nodes_neibs[k][index] in node2
                            if abs(weight - a_weight) / weight < 1e-5 and has1 is False and has2 is False:
                                node1.append(
                                    qualified_subgraphs_nodes_neibs[t][a_index])
                                node2.append(
                                    qualified_unique_subgraphs_nodes_neibs[k][index])
                                account += 1
                                break
                if account >= 3:
                    break
            if account >= 3:
                break
        if account < 3:
            print("can't find the corresspounding point")
            sys.exit()

        coords1 = [slab_supercell_sg.structure[n].coords for n in node1]
        coords2 = [bulk_super_structure_sg.structure[n].coords for n in node2]
        relative1 = np.array([np.array(coords1[n]) - np.array(coords1[0])
                              for n in list(range(1, 4))])
        relative2 = np.array([np.array(coords2[n]) - np.array(coords2[0])
                              for n in list(range(1, 4))])
        try:
            rotationMatrix = np.dot(relative1.T, np.linalg.inv(relative2.T))
        except np.linalg.LinAlgError as err:
            if 'Singular matrix' in str(err):
                for m in range(relative1.shape[0]):
                    if relative1[m, 0] == 0 and relative1[m, 1] == 0 and relative1[m, 2] == 0:
                        relative1[m, 0] = 1e-9
                        relative1[m, 2] = -1e-9
                for m in range(relative1.shape[1]):
                    if relative1[0, m] == 0 and relative1[1, m] == 0 and relative1[2, m] == 0:
                        relative1[0, m] = 1e-9
                        relative1[2, m] = -1e-9
                for m in range(relative2.shape[0]):
                    if relative2[m, 0] == 0 and relative2[m, 1] == 0 and relative2[m, 2] == 0:
                        relative2[m, 0] = 1e-9
                        relative2[m, 2] = -1e-9
                for m in range(relative2.shape[1]):
                    if relative2[0, m] == 0 and relative2[1, m] == 0 and relative2[2, m] == 0:
                        relative2[0, m] = 1e-9
                        relative2[2, m] = -1e-9
                rotationMatrix = np.dot(
                    relative1.T, np.linalg.inv(relative2.T))
            else:
                print('failed')
                sys.exit()
        relative = np.array([np.array(bulk_super_structure_sg.structure[n].coords)
                             - np.array(coords2[0])
                             for n in qualified_unique_subgraphs[i].nodes()])
        new_relatives = np.dot(rotationMatrix, relative.T).T
        coords = [np.array(coords1[0]) + new_relative
                  for new_relative in new_relatives]
        species = [bulk_super_structure_sg.structure[n].specie
                   for n in qualified_unique_subgraphs[i].nodes()]
        molecule = mg.Molecule(species=species, coords=coords)
        molecules_new.append(molecule)
    sites = []
    molecules_new_backup = list(molecules_new)
    if not fixed_c_negative:
        i = 0
        while i < len(molecules_new):
            under = False
            for curr_site in molecules_new[i]:
                curr_site = mg.PeriodicSite(curr_site.specie,
                                            curr_site.coords,
                                            slab.lattice,
                                            coords_are_cartesian=True)
                if curr_site.frac_coords[2] < c_frac_min:
                    del molecules_new[i]
                    under = True
                    break
            if under is False:
                i += 1
    if len(molecules_new) == 0:
        molecules_new = molecules_new_backup
    for molecule in molecules_new:
        for curr_site in molecule:
            curr_site = mg.PeriodicSite(curr_site.specie,
                                        curr_site.coords,
                                        slab.lattice,
                                        coords_are_cartesian=True)
            tmp = [curr_site.is_periodic_image(site) for site in sites]
            if not any(tmp):
                sites.append(curr_site)
    for site in sites:
        slab.append(species=site.specie, coords=site.coords,
                    coords_are_cartesian=True)
    return slab


def put_everyatom_into_cell(slab):
    """
    Some atoms might be out of the boundary of slab. Put all atoms into the
    boundary in the case that atoms don't overlap.
    """
    coords = slab.frac_coords
    for i in range(coords.shape[0]):
        for j in range(coords.shape[1]):
            coords[i, j] = coords[i, j] % 1
    species = slab.species
    molecule = mg.Molecule(species, coords)
    sites = []
    for site in molecule:
        site = mg.PeriodicSite(site.specie,
                               site.coords,
                               slab.lattice)
        tmp = [site.is_periodic_image(item, tolerance=1e-5) for item in sites]
        if not any(tmp):
            sites.append(site)
    delete_list = []
    for i, atom in enumerate(slab):
        delete_list.append(i)
    slab.remove_sites(delete_list)
    for site in sites:
        slab.append(species=site.specie, coords=site.coords,
                    coords_are_cartesian=True)
    return slab


def less_fix_broken_molecules(less_broken_subgraphs, less_intact_subgraphs,
                              bulk_super_structure_sg,
                              slab_supercell_sg,
                              slab, c_frac_min,
                              fixed_c_negative=True):
    """
    NOT used in the current reconstruction method!!!

    An optimized function of fix_broken_molecules() but does exactly the
    same thing. It can deal with more small broken molecules.
    """
    molecules_new = []
    for i in range(len(less_broken_subgraphs)):
        broken_subgraphs_species = []
        broken_subgraphs_nodes_neibs = []
        broken_subgraphs_weights = []
        nodes_broken_subgraphs = []
        for n, nbrs in less_broken_subgraphs[i].adjacency():
            nodes_broken_subgraphs.append(n)
            neibs = []
            weights = []
            broken_subgraphs_species.append(
                less_broken_subgraphs[i].node[n]['specie'])
            for nbr, eattr in nbrs.items():
                neibs.append(nbr)
                weights.append(eattr['weight'])
            broken_subgraphs_nodes_neibs.append(neibs)
            broken_subgraphs_weights.append(weights)
        intact_subgraphs_species = []
        intact_subgraphs_nodes_neibs = []
        intact_subgraphs_weights = []
        nodes_intact_subgraphs = []
        for n, nbrs in less_intact_subgraphs[i].adjacency():
            nodes_intact_subgraphs.append(n)
            neibs = []
            weights = []
            intact_subgraphs_species.append(
                less_intact_subgraphs[i].node[n]['specie'])
            for nbr, eattr in nbrs.items():
                neibs.append(nbr)
                weights.append(eattr['weight'])
            intact_subgraphs_nodes_neibs.append(neibs)
            intact_subgraphs_weights.append(weights)
        Find = False
        nodes1 = []
        nodes2 = []
        for j in range(len(broken_subgraphs_species)):
            if len(broken_subgraphs_nodes_neibs[j]) == 2:
                nodes1 = []
                weights1 = []
                nodes1.append(nodes_broken_subgraphs[j])
                for index, neib in enumerate(broken_subgraphs_nodes_neibs[j]):
                    nodes1.append(neib)
                    weights1.append(broken_subgraphs_weights[j][index])
                nodes2 = []
                for k in range(len(intact_subgraphs_species)):
                    if broken_subgraphs_species[j] == intact_subgraphs_species[k]\
                            and length_belong_to(broken_subgraphs_weights[j], intact_subgraphs_weights[k]):
                        nodes2.append(nodes_intact_subgraphs[k])
                        for index, weight in enumerate(weights1):
                            for index_intact, weight_intact in enumerate(intact_subgraphs_weights[k]):
                                if abs(weight - weight_intact) / weight_intact < 1e-5\
                                        and less_broken_subgraphs[i].\
                                        node[nodes1[index + 1]]['specie'] == less_intact_subgraphs[i].\
                                        node[intact_subgraphs_nodes_neibs[k][index_intact]]['specie']:
                                    nodes2.append(
                                        intact_subgraphs_nodes_neibs[k][index_intact])
                        if len(nodes2) == 3:
                            Find = True
                            break
            if Find is True:
                # print('Find it')
                break
        if Find is False:
            #print("Sucks")
            sys.exit()
        rest_item = -1
        rest_index = -1
        for index, item in enumerate(nodes_broken_subgraphs):
            if item not in nodes1:
                rest_item = item
                rest_index = index
        nodes1.append(rest_item)
        Find = False
        for j in range(len(intact_subgraphs_species)):
            if intact_subgraphs_species[j] == broken_subgraphs_species[rest_index]\
                    and length_belong_to(broken_subgraphs_weights[rest_index], intact_subgraphs_weights[j]):
                neibs = intact_subgraphs_nodes_neibs[j]
                temp = [neib == node2 for neib in neibs for node2 in nodes2]
                if any(temp):
                    nodes2.append(nodes_intact_subgraphs[j])
                    Find = True
                    break
        if Find is not True:
            print("didn't find the fourth one!")
            sys.exit()
        node1, node2 = nodes1, nodes2
        coords1 = [slab_supercell_sg.structure[n].coords for n in node1]
        coords2 = [bulk_super_structure_sg.structure[n].coords for n in node2]
        relative1 = np.array([np.array(coords1[n]) - np.array(coords1[0])
                              for n in list(range(1, 4))])
        relative2 = np.array([np.array(coords2[n]) - np.array(coords2[0])
                              for n in list(range(1, 4))])
        try:
            rotationMatrix = np.dot(relative1.T, np.linalg.inv(relative2.T))
        except np.linalg.LinAlgError as err:
            if 'Singular matrix' in str(err):
                for m in range(relative1.shape[0]):
                    if relative1[m, 0] == 0 and relative1[m, 1] == 0 and relative1[m, 2] == 0:
                        relative1[m, 0] = 1e-9
                        relative1[m, 2] = -1e-9
                for m in range(relative1.shape[1]):
                    if relative1[0, m] == 0 and relative1[1, m] == 0 and relative1[2, m] == 0:
                        relative1[0, m] = 1e-9
                        relative1[2, m] = -1e-9
                for m in range(relative2.shape[0]):
                    if relative2[m, 0] == 0 and relative2[m, 1] == 0 and relative2[m, 2] == 0:
                        relative2[m, 0] = 1e-9
                        relative2[m, 2] = -1e-9
                for m in range(relative2.shape[1]):
                    if relative2[0, m] == 0 and relative2[1, m] == 0 and relative2[2, m] == 0:
                        relative2[0, m] = 1e-9
                        relative2[2, m] = -1e-9
                rotationMatrix = np.dot(
                    relative1.T, np.linalg.inv(relative2.T))
            else:
                print('failed')
                sys.exit()
        relative = np.array([np.array(bulk_super_structure_sg.structure[n].coords)
                             - np.array(coords2[0])
                             for n in less_intact_subgraphs[i].nodes()])
        new_relatives = np.dot(rotationMatrix, relative.T).T
        coords = [np.array(coords1[0]) + new_relative
                  for new_relative in new_relatives]
        species = [bulk_super_structure_sg.structure[n].specie
                   for n in less_intact_subgraphs[i].nodes()]
        molecule = mg.Molecule(species=species, coords=coords)
        molecules_new.append(molecule)
    sites = []
    molecules_new_backup = list(molecules_new)
    if not fixed_c_negative:
        i = 0
        while i < len(molecules_new):
            under = False
            for curr_site in molecules_new[i]:
                curr_site = mg.PeriodicSite(curr_site.specie,
                                            curr_site.coords,
                                            slab.lattice,
                                            coords_are_cartesian=True)
                if curr_site.frac_coords[2] < c_frac_min:
                    del molecules_new[i]
                    under = True
                    break
            if under is False:
                i += 1
    if len(molecules_new) == 0:
        molecules_new = molecules_new_backup
    for molecule in molecules_new:
        for curr_site in molecule:
            curr_site = mg.PeriodicSite(curr_site.specie,
                                        curr_site.coords,
                                        slab.lattice,
                                        coords_are_cartesian=True)
            tmp = [curr_site.is_periodic_image(site) for site in sites]
            if not any(tmp):
                sites.append(curr_site)
    for site in sites:
        slab.append(species=site.specie, coords=site.coords,
                    coords_are_cartesian=True)
    return slab


def move_molecule(molecules, slab, delta):
    """
    Move molecules by a specific distance.

    Parameters: 
    -----------
    molecules: List[molecule].
        Molecules that need to be moved.
    slab: pymatgen structure.
        Slab after reconstruction process.
    delta: List[float].
        The distance those molecules should move in Cartesian Coordinates.

    Returns:
    --------
    slab: pymatgen structure.
    """
    coords = slab.cart_coords
    species = slab.species
    delete_sites = reduced_sites(molecules, slab)
    delete_list = []

    for delete_site in delete_sites:
        for i, atom in enumerate(slab):
            if atom.is_periodic_image(delete_site):
                delete_list.append(i)
                break
    slab.remove_sites(delete_list)

    for i in delete_list:
        new_coord = np.array(coords[i]) - np.array(delta)
        slab.append(species[i], new_coord, coords_are_cartesian=True)
    return slab


def double_find_the_gap(little_gap, big_gap, gaps, users_define_layers, tol):
    """
    Determine the fractional distance of two adajacent molecule groups in the c
    direction.

    Parameters:
    -----------
    little_gap: float (0, 1].
    big_gap: float [0, 1).
    gaps: List[float].
        the fractional distance of all sorted molecules in the c direction.
    users_define_layers: int.
        Possible number of groups in one-layer slab. Once the goups are
        defined, molecules in one group would move from one side to another
        simultaneously. The default number is None, means that each
        molecule makes up a group. 
    tol: float.
        Least difference between big and little gaps. i.e 1e-4.

    Returns:
    --------
    medium_gap: float.
        The fractional distance of two adajacent molecule groups. Return -1 if the function cannot determine this distance, i.e
    two groups are located in the same height.
    """
    if abs(big_gap - little_gap) < tol:
        return -1
    medium_gap = 0.5 * (little_gap + big_gap)
    qualified = np.sum([medium_gap < gap for gap in gaps])
    if qualified > users_define_layers - 1:
        return double_find_the_gap(medium_gap, big_gap, gaps, users_define_layers, tol)
    elif qualified < users_define_layers - 1:
        return double_find_the_gap(little_gap, medium_gap, gaps, users_define_layers, tol)
    else:
        return medium_gap


def number_of_molecules(slab):
    """
    Determine how many molecules are contained in the structure

    Parameters:
    -----------
    slab: pymatgen structure.
    
    Returns:
    --------
    len(molecules): int
    """
    slab_sg = StructureGraph.with_local_env_strategy(slab, JmolNN())
    bulk_sg = slab_sg * (1, 1, 1)
    _, molecules = get_bulk_subgraphs(bulk_structure_sg=bulk_sg)
    return len(molecules)


def delete_molecules(slab, working_directory, vacuum_size=None, num_to_delete=0):
    """
    Delete molecules from upper side to lower side to meet personal needs.

    Parameters:
    -----------
    slab: pymatgen structure.
    num_to_delete: int.
        num_to_delete < len(molecules)

    Returns:
    --------
    slab_delete: pymatgen structure.
    """
    if num_to_delete < 0:
        print("WARNING: num_to_delete >= 0.\nAlready set num_to_delete = 0")
        num_to_delete = 0
    if num_to_delete == 0:
        return slab
    if num_to_delete > 0:
        """Delete molecules after graph structure analysis"""
        slab_delete = deepcopy(slab)
        slab_sg = StructureGraph.with_local_env_strategy(slab_delete, JmolNN())
        bulk_sg = slab_sg * (1, 1, 1)
        _, molecules = get_bulk_subgraphs(bulk_structure_sg=bulk_sg)
        if num_to_delete > len(molecules):
            print("WARNING: num_to_delete > number_of_molecules.\nAlready set nunum_to_delete = 0")
            num_to_delete = 0
            return slab
        highest_z_location = [np.max(np.array(slab_delete.lattice.get_fractional_coords(molecule.cart_coords))[:, 2])
                             for molecule in molecules]
        [highest_z_location, molecules] = list(
            zip(*(sorted(zip(highest_z_location, molecules), key=lambda a: a[0], reverse=True)))
        )
        molecules_delete = molecules[:num_to_delete]
        delete_sites = reduced_sites(molecules_delete, slab_delete)
        delete_list = []

        for delete_site in delete_sites:
            for i, atom in enumerate(slab_delete):
                if atom.is_periodic_image(delete_site):
                    delete_list.append(i)
                    break
        slab_delete.remove_sites(delete_list)
        file_name = os.path.join(working_directory, "delete_layer.POSCAR.vasp")
        Poscar(slab_delete.get_sorted_structure()
               ).write_file(file_name)
        slab_delete_layer = io.read(file_name,parallel=False)
        os.remove(file_name)
        slab_delete_layer.center(vacuum=vacuum_size, axis=2)
        io.write(file_name, images=slab_delete_layer,parallel=False)
        modify_poscar(file_name)
        slab_delete = mg.Structure.from_file(file_name)
        os.remove(file_name)
        return slab_delete

