"""
File Overview: Implementation of the Crank-Nicolson Partial Differential Equation (PDE) solver for option pricing.
Provides unconditional numerical stability and O(M) tridiagonal sparse solving via SuperLU pre-factorization.
Domain Service layer (Pure financial mathematics).
"""

from typing import Optional
import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import splu


class CrankNicolsonPDE:
    """
    Solves the 1D Black-Scholes PDE using second-order Crank-Nicolson finite difference scheme
    with SuperLU pre-factorization.
    """

    def __init__(
        self,
        S0: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: str = "call",
        M: int = 300,
        N: int = 300,
    ) -> None:
        if S0 <= 0 or K <= 0:
            raise ValueError(f"Spot and strike must be positive, got S0={S0}, K={K}")

        self.S0 = float(S0)
        self.K = float(K)
        self.T = max(float(T), 1e-6)  # Guard against T=0
        self.r = float(r)
        self.sigma = max(float(sigma), 1e-6)
        self.option_type = option_type.lower()

        # Grid parameters (M: Price steps, N: Time steps)
        self.M = int(M)
        self.N = int(N)
        self.S_max = max(3.0 * self.K, 2.5 * self.S0)
        self.dS = self.S_max / float(self.M)
        self.dt = self.T / float(self.N)

    def solve(self) -> float:
        """
        Executes Crank-Nicolson PDE time-stepping and returns the fair option value.
        """
        # 1. Setup spatial grid nodes
        S_nodes = np.linspace(0.0, self.S_max, self.M + 1)

        # 2. Terminal Payoff (at maturity tau = 0)
        if self.option_type in ("call", "ce"):
            grid = np.maximum(S_nodes - self.K, 0.0)
        else:
            grid = np.maximum(self.K - S_nodes, 0.0)

        # 3. Tridiagonal Matrix Coefficients
        # For inner nodes i in [1, M-1]:
        i = np.arange(1, self.M, dtype=float)
        alpha = 0.25 * self.dt * ((self.sigma**2 * i**2) - (self.r * i))
        beta = 0.50 * self.dt * ((self.sigma**2 * i**2) + self.r)
        gamma = 0.25 * self.dt * ((self.sigma**2 * i**2) + (self.r * i))

        # Matrix A (Implicit LHS, time step j+1): -alpha on subdiag, (1+beta) on main, -gamma on superdiag
        A = diags([-alpha[1:], 1.0 + beta, -gamma[:-1]], [-1, 0, 1], shape=(self.M - 1, self.M - 1), format="csc")

        # Matrix B (Explicit RHS, time step j): alpha on subdiag, (1-beta) on main, gamma on superdiag
        B = diags([alpha[1:], 1.0 - beta, gamma[:-1]], [-1, 0, 1], shape=(self.M - 1, self.M - 1), format="csc")

        # Pre-factorize Matrix A via SuperLU for O(M) linear time backward steps
        A_solver = splu(A)

        # 4. Backward Time-Stepping Loop (tau = 0 -> T)
        for j in range(self.N):
            rhs = B.dot(grid[1:self.M])
            tau_old = j * self.dt
            tau_new = (j + 1) * self.dt

            if self.option_type in ("call", "ce"):
                # Call boundary: S=0 -> 0; S=S_max -> S_max - K*exp(-r*tau)
                v_old_top = self.S_max - self.K * np.exp(-self.r * tau_old)
                v_new_top = self.S_max - self.K * np.exp(-self.r * tau_new)
                rhs[-1] += gamma[-1] * (v_old_top + v_new_top)
            else:
                # Put boundary: S=0 -> K*exp(-r*tau); S=S_max -> 0
                v_old_bottom = self.K * np.exp(-self.r * tau_old)
                v_new_bottom = self.K * np.exp(-self.r * tau_new)
                rhs[0] += alpha[0] * (v_old_bottom + v_new_bottom)

            # Solve linear system in O(M) time
            grid[1:self.M] = A_solver.solve(rhs)

        # 5. Interpolate option value at exact S0
        fair_price = float(np.interp(self.S0, S_nodes, grid))
        return float(max(fair_price, 0.0))
