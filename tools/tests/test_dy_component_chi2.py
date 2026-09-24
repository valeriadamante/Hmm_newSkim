"""Numerical regression for the weighted component fit."""
import numpy as np
import pytest
from tools.derive_dy_012j_reweight import solve_nonnegative_chi2


def test_chi2_matches_weighted_linear_solution():
    matrix = np.array([[2., 0.], [0., 3.], [1., 2.], [4., 1.]])
    variance = np.array([1., 4., 2., 3.])
    background = np.full(4, 5.)
    data = background + matrix @ [1.3, .7] + [.1, -.2, .3, -.1]
    precision = np.diag(1 / variance)
    expected_cov = np.linalg.inv(matrix.T @ precision @ matrix)
    expected = expected_cov @ matrix.T @ precision @ (data - background)
    theta, cov, chi2, ndof, valid = solve_nonnegative_chi2(data, background, matrix, variance)
    np.testing.assert_allclose(theta, expected)
    np.testing.assert_allclose(cov, expected_cov)
    assert chi2 == pytest.approx(np.sum((data - background - matrix @ theta)**2 / variance))
    assert ndof == 2 and valid.all()


def test_chi2_excludes_zero_variance_and_bounds_scales():
    theta, _, chi2, ndof, valid = solve_nonnegative_chi2(
        np.array([0., 0., 100.]), np.ones(3), np.ones((3, 1)), np.array([1., 1., 0.]))
    assert theta[0] == 0 and chi2 == pytest.approx(2.) and ndof == 1
    assert valid.tolist() == [True, True, False]


def test_chi2_rejects_degenerate_templates():
    with pytest.raises(RuntimeError, match='independent'):
        solve_nonnegative_chi2(np.ones(4), np.zeros(4), np.ones((4, 2)), np.ones(4))
