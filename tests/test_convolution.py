import mitsuba as mi
import drjit as dr
import pytest

import drtvam
from drtvam.convolution import make_drjit_conv
import numpy as np
import matplotlib.pyplot as plt

@pytest.mark.parametrize("variant", ["cuda_ad_mono"])
def test_mitsuba_convolution(variant):
    mi.set_variant(variant)
    # Parameters
    spacing = 5e-3
    D = 10e-6
    dt = 10
    radius = 20
    size = 40   # 21

    # Build kernel
    conv = make_drjit_conv(spacing * 3, spacing * 1, spacing * 2, D, dt,
                           radiusz=radius, radiusx=radius, radiusy=radius)

    # Input: 3D array with a single 1 at the center
    arr = dr.reshape(mi.TensorXf(dr.zeros(mi.Float, size * size *  size)), (size, size, size, 1))
    arr[size//2, size//2, size//2] = 1.0
    r = arr

    # Convolve
    result = conv(r)
    result_np = (result)

    # plt.imshow(np.sum(result, axis=3)[:, :, size//2])
    # plt.colorbar()
    # plt.show()

    # Build expected kernel analytically (separable outer product)
    idx = mi.TensorXf(dr.arange(mi.Float, -radius, radius + 1) * spacing)[:-1]
    idy = mi.TensorXf(dr.arange(mi.Float, -radius, radius + 1) * spacing * 2)[:-1]
    idz = mi.TensorXf(dr.arange(mi.Float, -radius, radius + 1) * spacing * 3)[:-1]
    k1x = dr.exp(-(idx**2 / (4 * D * dt)))
    k1x /= dr.sum(k1x)
    k1y = dr.exp(-(idy**2 / (4 * D * dt)))
    k1y /= dr.sum(k1y)
    k1z = dr.exp(-(idz**2 / (4 * D * dt)))
    k1z /= dr.sum(k1z)

    print(k1z)
    kernel_3d = k1z[:, None, None, None] * k1x[None, :, None, None] * k1y[None, None, :, None]
    kernel_3d /= dr.sum(kernel_3d)

    # plt.imshow(np.sum(kernel_3d, axis=3)[:, :, size//2])
    # plt.colorbar()
    # plt.show()

    # Compare
    max_err = dr.max(dr.abs(result_np - kernel_3d))
    assert dr.abs(dr.sum(result) - 1.0) < 1e-6, "Convolution result is not normalized!"
    assert dr.abs(dr.sum(kernel_3d) - 1.0) < 1e-6, "Expected kernel is not normalized!"
    assert max_err < 1e-6, "Convolution result does not match expected kernel!"
    assert dr.allclose(result_np, kernel_3d, atol=1e-6), "Convolution result does not match expected kernel!"
