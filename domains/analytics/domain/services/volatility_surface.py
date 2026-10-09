"""
File Overview: Volatility Surface Domain Service.
Constructs a smooth implied volatility smile/surface across option strikes using cubic splines.
Breaks the volatility circularity problem by providing an independent, surface-interpolated
volatility parameter for theoretical PDE fair-value pricing.
"""

from typing import List, Optional, Tuple
import numpy as np
from scipy.interpolate import CubicSpline

from domains.analytics.domain.services.pde_solver import CrankNicolsonPDE


class VolatilitySurface:
    """
    Constructs a calibrated implied volatility surface from discrete market strikes
    using natural cubic spline interpolation.
    """

    MIN_STRIKES_REQUIRED: int = 4
    MIN_VOLATILITY: float = 0.02   # 2.0% annual vol lower bound
    MAX_VOLATILITY: float = 3.00   # 300.0% annual vol upper bound

    def __init__(
        self,
        strikes: List[float],
        ivs: List[float],
        spot: float,
        expiry_years: Optional[float] = None,
    ) -> None:
        """
        Initialize and fit cubic spline volatility surface.

        Args:
            strikes: List of option strike prices.
            ivs: Corresponding implied volatilities (e.g. 0.15 for 15% IV).
            spot: Current underlying asset spot price.
            expiry_years: Optional time to expiry in years.
        """
        if spot <= 0:
            raise ValueError(f"Spot price must be positive, got {spot}")

        self.spot = float(spot)
        self.expiry_years = float(expiry_years) if expiry_years is not None else None

        # Clean and filter pairs
        valid_pairs: List[Tuple[float, float]] = []
        for k, v in zip(strikes, ivs):
            if k is not None and v is not None:
                k_val = float(k)
                v_val = float(v)
                # If IV is passed as percentage (e.g. 18.5 instead of 0.185), normalize to decimal
                if v_val > 5.0:
                    v_val = v_val / 100.0

                if k_val > 0 and self.MIN_VOLATILITY <= v_val <= self.MAX_VOLATILITY:
                    valid_pairs.append((k_val, v_val))

        # Sort and deduplicate by strike
        valid_pairs.sort(key=lambda item: item[0])
        unique_strikes: List[float] = []
        unique_ivs: List[float] = []
        for k, v in valid_pairs:
            if not unique_strikes or k != unique_strikes[-1]:
                unique_strikes.append(k)
                unique_ivs.append(v)

        self._strikes = np.array(unique_strikes, dtype=float)
        self._ivs = np.array(unique_ivs, dtype=float)

        if len(self._strikes) >= self.MIN_STRIKES_REQUIRED:
            self._spline: Optional[CubicSpline] = CubicSpline(
                self._strikes, self._ivs, bc_type="natural", extrapolate=True
            )
        else:
            self._spline = None
            self._fallback_iv: float = float(np.mean(self._ivs)) if len(self._ivs) > 0 else 0.20

    @property
    def is_fitted(self) -> bool:
        """Returns True if the cubic spline was successfully fitted across enough strikes."""
        return self._spline is not None

    @property
    def strike_count(self) -> int:
        return len(self._strikes)

    def get_surface_iv(self, strike: float) -> float:
        """
        Return the smooth surface-interpolated IV for a given strike.
        Clamps extrapolation to prevent extreme polynomial boundary flare.
        """
        if strike <= 0:
            return self._fallback_iv if not self.is_fitted else float(self._ivs[0])

        if not self.is_fitted:
            return self._fallback_iv

        # Natural spline evaluation
        raw_iv = float(self._spline(strike))

        # Clamp boundary extrapolation to edge values ± 50%
        min_iv_observed = float(np.min(self._ivs))
        max_iv_observed = float(np.max(self._ivs))
        lower_clamp = max(self.MIN_VOLATILITY, min_iv_observed * 0.5)
        upper_clamp = min(self.MAX_VOLATILITY, max_iv_observed * 1.5)

        clamped_iv = max(lower_clamp, min(upper_clamp, raw_iv))
        return float(round(clamped_iv, 6))

    def get_atm_iv(self) -> float:
        """Return implied volatility interpolated at exact ATM spot price."""
        return self.get_surface_iv(self.spot)

    def compute_pde_fair_value(
        self,
        strike: float,
        spot: float,
        expiry_years: float,
        rate: float,
        option_type: str = "call",
        grid_m: int = 200,
        grid_n: int = 200,
    ) -> float:
        """
        Solve Crank-Nicolson PDE fair value using the smooth surface-calibrated IV.
        """
        surface_iv = self.get_surface_iv(strike)
        solver = CrankNicolsonPDE(
            S0=spot,
            K=strike,
            T=expiry_years,
            r=rate,
            sigma=surface_iv,
            option_type=option_type,
            M=grid_m,
            N=grid_n,
        )
        return float(solver.solve())

    def get_mispricing(
        self,
        strike: float,
        market_price: float,
        spot: float,
        expiry_years: float,
        rate: float,
        option_type: str = "call",
        grid_m: int = 200,
        grid_n: int = 200,
    ) -> float:
        """
        Compute theoretical mispricing: delta = MarketPrice - C_PDE(Surface_IV).
        
        A negative delta indicates the option is UNDERVALUED in the market (buying opportunity).
        A positive delta indicates the option is OVERVALUED in the market (overpriced premium).
        """
        if market_price <= 0:
            return 0.0

        pde_fair_value = self.compute_pde_fair_value(
            strike=strike,
            spot=spot,
            expiry_years=expiry_years,
            rate=rate,
            option_type=option_type,
            grid_m=grid_m,
            grid_n=grid_n,
        )
        return float(round(market_price - pde_fair_value, 4))
