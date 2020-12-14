from tqdm import tqdm
import glob
import os
import logging
import io
import copy
import shutil
from openff.benchmark.utils.generate_conformers import align_offmol_conformers, greedy_conf_deduplication
from rdkit import Chem

logger = logging.getLogger('openforcefield.utils.toolkits')
prev_log_level = logger.getEffectiveLevel()
logger.setLevel(logging.ERROR)

from openforcefield.topology import Molecule
from openforcefield.utils.toolkits import GLOBAL_TOOLKIT_REGISTRY, OpenEyeToolkitWrapper

logger.setLevel(prev_log_level)


from .io import mols_from_paths

#logger = logging.logger()

oetk_loaded = False
for tkw in GLOBAL_TOOLKIT_REGISTRY.registered_toolkits:
    if isinstance(tkw, OpenEyeToolkitWrapper):
        oetk_loaded = True
if oetk_loaded:
    GLOBAL_TOOLKIT_REGISTRY.deregister_toolkit(OpenEyeToolkitWrapper)
    
def validate_and_assign(#input_graph_files,
                        input_3d_files,
                        group_name,
                        output_directory='1-validate_and_assign',
                        delete_existing=False):
    
    try:
        os.makedirs(output_directory)
    except OSError:
        if delete_existing:
            shutil.rmtree(output_directory)
            os.makedirs(output_directory)
        else:
            raise Exception(f'Output directory {output_directory} already exists. '
                             'Specify `delete_existing=True` to remove.')

    logging.basicConfig(filename=os.path.join(output_directory,'log.txt'),
                        level=logging.DEBUG)
    #this_logger = logging.getLogger(__name__)
        
    smiles2mol = {}
    error_mols = []

            
    # Handle 3d molecules
    print('Reading input files and validating structures')
    for molecule_3d_file in input_3d_files:
        print(f"Reading {molecule_3d_file}")
        toolkit_logger = logging.getLogger('openforcefield.utils.toolkits')
        prev_log_level = toolkit_logger.getEffectiveLevel()
        toolkit_logger.setLevel(logging.ERROR)

        #loaded_mols = mols_from_paths([molecule_3d_file])
        loaded_mols = Molecule.from_file(molecule_3d_file,
                                         file_format='sdf',
                                         allow_undefined_stereo=True)
        toolkit_logger.setLevel(prev_log_level)
        if not isinstance(loaded_mols, list):
            loaded_mols = [loaded_mols]
        print("Validating contents")
        for mol_index, mol in tqdm(enumerate(loaded_mols)):
            # Simulate a SDF file roundtrip to check for errors such as undefined stereochemistry
            try:
                sio = io.StringIO()
                mol.to_file(sio, file_format='sdf')
                sio.seek(0)
                bio = io.BytesIO(sio.read().encode('utf8'))
                Molecule.from_file(bio, file_format='sdf')
            except Exception as e:
                error_mols.append((f'{molecule_3d_file}:{mol_index}', mol, e))
                continue

            # Sanitize any information that might already be present
            # TODO: log mapping of input names/properties to output mols
            keys = list(mol.properties.keys())
            for key in keys:
                mol.properties.pop(key)
            mol.partial_charges = None
            
            # If this graph molecule IS already known, add this 3d information as a conformer
            smiles = mol.to_smiles()
            if smiles in smiles2mol:
                orig_mol = smiles2mol[smiles]
                _, atom_map = Molecule.are_isomorphic(mol,
                                                      orig_mol,
                                                      return_atom_map=True,
                                                      formal_charge_matching=False,
                                                      aromatic_matching=False,
                                                      #atom_stereochemistry_matching=False,
                                                      #bond_stereochemistry_matching=False,
                                                      )
                reordered_mol = mol.remap(atom_map)
                # Make a temporary copy of the parent mol for conformer alignment and deduplication
                temp_mol = Molecule(orig_mol)
                temp_mol.add_conformer(reordered_mol.conformers[0])
                aligned_mol, rmslist = align_offmol_conformers(temp_mol)
                # Don't trust rmslist above for deduplication -- It doesn't take into
                # account multiple atom mappings
                confs_to_delete = greedy_conf_deduplication(temp_mol,
                                                            0.1)
                if len(confs_to_delete) > 0:
                    msg = f'Duplicate molecule conformer input detected.\n'
                    msg += f'{molecule_3d_file}:{mol_index} has an RMSD within 0.1 A '
                    msg += f'to the molecule originally loaded from '
                    msg += f'{orig_mol.properties["original_files"]}:{orig_mol.properties["original_file_indices"]}'
                    logging.warning(msg)
                    temp_mol._conformers = [temp_mol.conformers[-1]]
                    error_mols.append((f'{molecule_3d_file}:{mol_index}', mol, msg))
                    continue
                # Append the most recent file info to the provenance properties
                # These properties will be in the same order as the molecule's conformers.
                temp_mol.properties['original_files'].append(molecule_3d_file)
                temp_mol.properties['original_file_indices'].append(mol_index)
                temp_mol.properties['original_names'].append(mol.name)
                
                smiles2mol[smiles] = temp_mol
                
            # If this graph molecule ISN'T already known, then add
            # this representation as a new molecule
            else:
                # Keep a record of the context from which this was loaded
                mol.properties['original_files'] = [molecule_3d_file]
                mol.properties['original_file_indices'] = [mol_index]
                mol.properties['original_names'] = [mol.name]
                mol.name = None
                smiles2mol[smiles] = mol                

    
    # Assign names and write out files
    # Preserve a mapping of input filename/mol index to output name
    name_assignments = []
    print("Assigning IDs and writing out validated files")
    for unique_mol_index, smiles in tqdm(enumerate(smiles2mol.keys())):
        mol_name = f'{group_name}-{unique_mol_index:05d}'
        smiles2mol[smiles].properties['group_name'] = group_name
        smiles2mol[smiles].properties['molecule_index'] = unique_mol_index
        smiles2mol[smiles].name = mol_name
        mol_copy = Molecule(smiles2mol[smiles])

        # Pop off now-nonessential metadata
        mol_copy.properties.pop('original_files')
        mol_copy.properties.pop('original_file_indices')
        mol_copy.properties.pop('original_names')

        # Write conformers
        for conf_index, conformer in enumerate(smiles2mol[smiles].conformers):
            out_file_name = f'{mol_copy.name}-{conf_index:02d}.sdf'

            orig_file = smiles2mol[smiles].properties['original_files'][conf_index]
            orig_file_index = smiles2mol[smiles].properties['original_file_indices'][conf_index]
            orig_name = smiles2mol[smiles].properties['original_names'][conf_index]
            msg = f'Molecule with name {orig_name} from '
            msg += f'file:position {orig_file}:{orig_file_index}'
            msg += f' has passed validation '
            msg += f'and is being written to file {out_file_name}.'
            logging.info(msg)

            name_assignments.append((orig_name, orig_file, orig_file_index, out_file_name))
            mol_copy._conformers = None
            mol_copy.add_conformer(conformer)
            mol_copy.properties['conformer_index'] = conf_index
            mol_copy.to_file(os.path.join(output_directory, out_file_name), file_format='sdf')

    # Write name assignments
    with open(os.path.join(output_directory, 'name_assignments.csv'), 'w') as of:
        of.write('orig_name,orig_file,orig_file_index,out_file_name\n')
        for name_assignment in name_assignments:
            of.write(','.join([str(i) for i in name_assignment]))
            of.write('\n')

    # Create error directory
    error_dir = os.path.join(output_directory, 'error_mols')
    os.makedirs(error_dir)

    
    # Write error mols
    for idx, (filename, error_mol, exception) in enumerate(error_mols):
        output_mol_file = os.path.join(error_dir, f'error_mol_{idx}.sdf')
        try:
            error_mol.to_file(output_mol_file, file_format='sdf')
        except Exception as e:
            exception = str(exception)
            exception += "\n Then failed when trying to write mol to error directory with "
            exception += str(e)
        output_summary_file = os.path.join(error_dir, f'error_mol_{idx}.txt')
        with open(output_summary_file, 'w') as of:
            of.write(f'source: {filename}\n')
            of.write(f'error text: {exception}\n')
                  
        
    
if __name__ == '__main__':
    validate_and_assign()
