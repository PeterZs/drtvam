import torch
import drjit as dr
import mitsuba as mi
import numpy as np
import os

from drtvam.diffusion import fft_convolve_3d

def assemble_physical_forward_model(config):
    if "physical_model" in config and config["physical_model"]["type"] == "inhibitor":
        inhibitor_0 = dr.ones(mi.TensorXf,
                              shape=(config["sensor"]["film"]["resz"],
                                     config["sensor"]["film"]["resx"],
                                     config["sensor"]["film"]["resy"],1))
        if "inhibitor_init" in config["physical_model"]:
            print("Loading inhibitor initial state from",
                  config["physical_model"]["inhibitor_init"])
            inhibitor_0 *= mi.TensorXf(np.load(config["physical_model"]["inhibitor_init"]))

        def physical_fwd(light_dose):
            q_inhibitor = dr.minimum(light_dose, inhibitor_0)
            inhibitor = inhibitor_0 - q_inhibitor
            polymerization = light_dose - q_inhibitor
            return polymerization, inhibitor

    elif "physical_model" in config and config["physical_model"]["type"] == "inhibitor_diffusion":
        print(config["physical_model"])
        inhibitor_0 = dr.ones(mi.TensorXf,
                              shape=(config["sensor"]["film"]["resz"],
                                     config["sensor"]["film"]["resx"],
                                     config["sensor"]["film"]["resy"],1))
        if "inhibitor_init" in config["physical_model"]:
            print("Loading inhibitor initial state from",
                  config["physical_model"]["inhibitor_init"])
            inhibitor_0 *= mi.TensorXf(np.load(config["physical_model"]["inhibitor_init"]))

        print("Using diffusion model for inhibition.")
        diffusion_D = config['physical_model']['diffusion_coefficient']
        diffusion_time = config['print_time']
        diffusion_number_rotations = config['physical_model']['number_time_steps']

        assert config['sensor']['film']["resz"] % 2 == 0, "Currently only even number of z slices supported for diffusion model."
        assert config['sensor']['film']["resx"] % 2 == 0, "Currently only even number of x slices supported for diffusion model."
        assert config['sensor']['film']["resy"] % 2 == 0, "Currently only even number of y slices supported for diffusion model."

        # endpoint false is required to center kernel correctly
        x = torch.linspace(-config['sensor']['scalex'] / 2,
                           config['sensor']['scalex'] / 2,
                           config['sensor']['film']['resx']+1)[:-1].to('cuda')
        y = torch.linspace(-config['sensor']['scaley'] / 2,
                           config['sensor']['scaley'] / 2,
                           config['sensor']['film']['resy']+1)[:-1].to('cuda')
        z = torch.linspace(-config['sensor']['scalez'] / 2,
                           config['sensor']['scalez'] / 2,
                           config['sensor']['film']['resz']+1)[:-1].to('cuda')

        X, Y, Z = torch.meshgrid(z, x, y, indexing='ij')


        delta_t = diffusion_time / diffusion_number_rotations
        r = torch.sqrt(X**2 + Y**2 + Z**2)

        diffusion_kernel = torch.exp(-r**2 / (4 * diffusion_D * delta_t))
        diffusion_kernel /= torch.sum(diffusion_kernel)

        diffusion_kernel = torch.fft.ifftshift(diffusion_kernel)
        diffusion_kernel = diffusion_kernel[:, :, :, None]

        diffusion_kernel_drjit = dr.cuda.TensorXf(diffusion_kernel)
        np.save(os.path.join(config["output"], "diffusion_kernel.npy"),
                np.fft.fftshift(diffusion_kernel_drjit.numpy()))



        def physical_fwd(light_dose):
            # see https://drjit.readthedocs.io/en/stable/autodiff.html#differentiating-loops
            def loop(light_dose, diffusion_number_rotations):
                inhibitor = inhibitor_0
                polymerization = 0 * inhibitor
                i = 0

                light_dose_loop = light_dose / diffusion_number_rotations
                while dr.hint(i < diffusion_number_rotations, max_iterations=-1):
                    q_inhibitor = dr.minimum(light_dose_loop, inhibitor)
                    inhibitor = inhibitor - q_inhibitor
                    radicals = light_dose_loop - q_inhibitor
                    polymerization += radicals
                    # Diffusion step
                    inhibitor = fft_convolve_3d(inhibitor,
                                                diffusion_kernel_drjit)
                    i += 1

                return polymerization, inhibitor
            return loop(light_dose, diffusion_number_rotations)
    else:
        # default cause, just return light dose
        def physical_fwd(light_dose):
            return (light_dose, )

    return physical_fwd
