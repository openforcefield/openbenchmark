from openff.benchmark.utils.generate_conformers import generate_conformers
import inspect
import os
import pytest
import glob
import shutil
from openff.benchmark.utils.utils import get_data_file_path
from openforcefield.utils.toolkits import GLOBAL_TOOLKIT_REGISTRY, OpenEyeToolkitWrapper, RDKitToolkitWrapper


def test_openeye_deregistered():
    for toolkitwrapper in GLOBAL_TOOLKIT_REGISTRY.registered_toolkits:
        assert not isinstance(toolkitwrapper, OpenEyeToolkitWrapper)
    to_smiles = GLOBAL_TOOLKIT_REGISTRY.resolve('to_smiles')
    assert not isinstance(to_smiles.__self__, OpenEyeToolkitWrapper)
    assert isinstance(to_smiles.__self__, RDKitToolkitWrapper)


def test_dont_overwrite_output_directory():
    test_name = inspect.stack()[0].function
    input_dir = get_data_file_path('1-validate_and_assign_graphs_and_confs')
    output_dir = os.path.join(test_name, '2-generate_conformers')
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    generate_conformers(input_dir,
                        output_dir,
                        )
    with pytest.raises(Exception, match='delete this manually'):
        generate_conformers(input_dir,
                            output_dir,
        )


# test loading a mix of graph and 3D molecules, generating up to 10 confs
def test_generate_conformers():
    test_name = inspect.stack()[0].function
    input_dir = get_data_file_path('1-validate_and_assign_graphs_and_confs')
    output_dir = os.path.join(test_name, '2-generate_conformers')
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
        
    generate_conformers(input_dir, output_dir)
    
    # Make sure the graph mol is present in the output
    for mol_idx in range(5):
        assert os.path.exists(os.path.join(output_dir, f'BBB-{mol_idx:05d}.smi'))
        # Make sure the mapped smiles is identical before and after
        input_mapped_smiles = open(os.path.join(input_dir, f'BBB-{mol_idx:05d}.smi')).read()
        output_mapped_smiles = open(os.path.join(output_dir, f'BBB-{mol_idx:05d}.smi')).read()
        assert input_mapped_smiles == output_mapped_smiles
        
    ## BBB-00000 starts with a smi and two conformers, so many more conformers should be created
    bbb0_confs = glob.glob(os.path.join(output_dir, 'BBB-00000-*.sdf'))
    assert len(bbb0_confs) > 3

    ## BBB-00001 starts with a smi and one conformer, so many more conformers should be created
    bbb1_confs = glob.glob(os.path.join(output_dir, 'BBB-00001-*.sdf'))
    assert len(bbb1_confs) > 2

    ## BBB-00002 starts with a smi and NO conformers.
    # It is rigid so only one conformer should be created
    bbb2_confs = glob.glob(os.path.join(output_dir, 'BBB-00002-*.sdf'))
    assert len(bbb2_confs) == 1

    ## BBB-00003 starts with a smi and 12 conformers.
    # The last two conformers should be pruned and 10 conformers should be output
    bbb3_confs = glob.glob(os.path.join(output_dir, 'BBB-00003-*.sdf'))
    assert len(bbb3_confs) == 10

    ## BBB-00004 starts with a smi and NO conformers.
    # It is very flexible so 10 conformers should be output.
    bbb4_confs = glob.glob(os.path.join(output_dir, 'BBB-00004-*.sdf'))
    assert len(bbb4_confs) == 10

    ## BBB-00005 is a molecule with one torsional degree of freedom.
    # It has 2 possible distinct conformations at an RMS cutoff of 2A.
    # One of these conformations is provided, so two total should be output. 
    bbb4_confs = glob.glob(os.path.join(output_dir, 'BBB-00005-*.sdf'))
    assert len(bbb4_confs) == 2


# test loading a molecule where the pre-existing conformer displaces one of the generated conformers


