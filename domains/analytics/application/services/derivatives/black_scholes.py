"""
File Overview: Implementation of the Black-Scholes-Merton (BSM) closed-form analytical pricing formula.

Key Functions/Classes:
- BlackScholesMerton: Main class for BSM analytical model pricing.
- solve: Computes the exact call or put option price.

Endpoints/APIs: None

Database Tables: None
"""

import numpy as np
from scipy.stats import norm

class BlackScholesMerton:
    """
    Closed-form analytical solution for European options pricing using the BSM model.
    """
    def __init__(self, S0: float, K: float, T: float, r: float, sigma: float, option_type: str = 'call', q: float = 0.0):
        self.S0 = S0
        self.K = K
        self.T = max(T, 1e-6)  # Guard against T=0
        self.r = r
        self.sigma = max(sigma, 1e-6)  # Guard against sigma=0
        self.option_type = option_type.lower()
        self.q = q

    def solve(self) -> float:
        """
        Solve the Black-Scholes-Merton formula to get the theoretical option price.
        """
        if self.S0 <= 0 or self.K <= 0:
            return 0.0

        d_1 = (np.log(self.S0 / self.K) + (self.r - self.q + 0.5 * self.sigma ** 2) * self.T) / (self.sigma * np.sqrt(self.T))
        d_2 = d_1 - self.sigma * np.sqrt(self.T)

        if self.option_type == 'call':
            price = self.S0 * np.exp(-self.q * self.T) * norm.cdf(d_1) - self.K * np.exp(-self.r * self.T) * norm.cdf(d_2)
            return float(max(price, 0.0))
        elif self.option_type == 'put':
            price = self.K * np.exp(-self.r * self.T) * norm.cdf(-d_2) - self.S0 * np.exp(-self.q * self.T) * norm.cdf(-d_1)
            return float(max(price, 0.0))
        else:
            raise ValueError(f"Invalid option type: {self.option_type}. Must be 'call' or 'put'.")
