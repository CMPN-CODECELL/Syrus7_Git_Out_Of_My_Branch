"""
File Overview: Application adapter/re-export for the Crank-Nicolson Partial Differential Equation (PDE) solver.
Re-exports CrankNicolsonPDE from domain services for backward-compatibility.
"""

from domains.analytics.domain.services.pde_solver import CrankNicolsonPDE

__all__ = ["CrankNicolsonPDE"]
