"""Calculs géométriques sur des repères 2D en pixels."""

from math import atan2, degrees, hypot, isfinite

from packages.contracts.models import Point2D


def normalized_to_pixel(point: Point2D, width_px: int, height_px: int) -> tuple[float, float]:
    """Convertir chaque axe avec sa propre dimension avant tout calcul d'angle."""
    if width_px <= 0 or height_px <= 0:
        raise ValueError("Dimensions invalides")
    if not (0 <= point.x <= 1 and 0 <= point.y <= 1):
        raise ValueError("Repère hors image")
    return point.x * width_px, point.y * height_px


def internal_angle_deg(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    """Angle interne A-B-C dans [0, 180] ; rejette les segments dégénérés."""
    values = (*a, *b, *c)
    if not all(isfinite(value) for value in values):
        raise ValueError("Coordonnées non finies")
    ux, uy = a[0] - b[0], a[1] - b[1]
    vx, vy = c[0] - b[0], c[1] - b[1]
    if hypot(ux, uy) < 1e-6 or hypot(vx, vy) < 1e-6:
        raise ValueError("Segment dégénéré")
    cross = ux * vy - uy * vx
    dot = ux * vx + uy * vy
    return degrees(atan2(abs(cross), dot))


def apparent_elbow_flexion_deg(
    shoulder: Point2D, elbow: Point2D, wrist: Point2D, width_px: int, height_px: int
) -> float:
    """Convention expérimentale : 180° moins l'angle interne apparent du coude.

    Ne mesure pas l'hyperextension signée ni l'amplitude articulaire anatomique.
    """
    a, b, c = (
        normalized_to_pixel(point, width_px, height_px)
        for point in (shoulder, elbow, wrist)
    )
    return 180.0 - internal_angle_deg(a, b, c)
