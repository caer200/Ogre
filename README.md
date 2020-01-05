# Ogre
Ogre is written in Python 3 and uses  the  ase, and  pymatgen libraries.   The  code  is under a BSD-3license license.  Ogre takes a bulk crystalstructure as input. Several common structure input formats are supported, including CIF, VASP POSCAR files, and FHI-aims geometry.in files. Ogre generates surface slabs by cleaving thebulk crystal along a user-specified Miller plane. Ogre outputs surface slab models with the number of layers and amount of vacuum requested by the user. 
## Installation
```bash
conda create python=3.7 -n ogre
conda activate ogre
pip install -r requirements.txt
```
This code might crash if you use the newest version of pymatgen, so please use the version specified in requirements.txt

## Example
In example directory run example.py to do test: 

```bash
python example.py
```
