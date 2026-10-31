"""Example animation: a Team A (Type 1) skater does one lap of the rink.

The skater starts at the top middle of the ice and skates counter-clockwise:
left along the top boards, down behind the left goal, along the bottom boards,
up behind the right goal and back to where it started.

Press SPACE to skate another lap, ESC to quit.
"""
import bisect
import math
from pathlib import Path

import pygame

ASSETS = Path(__file__).parent / "NES_Ice_Hockey_Full_Files" / "NES Ice Hockey Full Files"
RINK_IMAGE = ASSETS / "Ice Hockey Rink Tile Set" / "NES_IceHockey_IceRink_WithGoal.png"
SKATE_FRAMES = ASSETS / "Team A Type 1" / "Skate Frames"

FPS = 60
FRAME_WIDTH = 24      # every skate strip holds 4 frames, each 24 px wide
SKATE_SPEED = 100     # pixels per second
STRIDE_LENGTH = 12    # pixels travelled per animation frame
START_PAUSE = 1.0     # seconds to stand still before setting off

# Compass names in order of angle / 45 degrees (0 = east, counter-clockwise),
# matching the Team_A_T1_PSkate_<Direction>_strip4.png file names.
DIRECTIONS = ["East", "NorthEast", "North", "NorthWest", "West", "SouthWest", "South", "SouthEast"]

# The rink is drawn in perspective: the end boards lean outwards by half a pixel
# for every pixel further down the screen. The lap is planned in a flat "rink
# space" (x measured in pixels along the middle row of the ice) and skewed onto
# the screen, so the skater follows the boards at an even distance.
RINK_CENTER_X = 355.5
ICE_MID_Y = 128

# The lap is a rounded rectangle in rink space. LAP_HALF_LENGTH puts the skater
# midway between each goal net and the end boards.
LAP_HALF_LENGTH = 282
LAP_TOP = 56
LAP_BOTTOM = 203
CORNER_RADIUS = 50
CORNER_STEPS = 16


def half_width(y):
    """Distance on screen row y from the centre line to the end boards."""
    return 231.5 + 0.5 * y


def rink_to_screen(x, y):
    return RINK_CENTER_X + x * half_width(y) / half_width(ICE_MID_Y), y


def facing(dx, dy):
    """Index into DIRECTIONS closest to a movement vector (y pointing down)."""
    angle = math.degrees(math.atan2(-dy, dx))
    return round(angle / 45) % len(DIRECTIONS)


def build_lap():
    """Rink-space points of one counter-clockwise lap, starting at the top middle."""
    left = -LAP_HALF_LENGTH + CORNER_RADIUS
    right = LAP_HALF_LENGTH - CORNER_RADIUS
    top = LAP_TOP + CORNER_RADIUS
    bottom = LAP_BOTTOM - CORNER_RADIUS
    # Each corner sweeps 90 degrees. Screen y points down, so going
    # counter-clockwise on screen means the angle decreases.
    corners = [((left, top), 270), ((left, bottom), 180), ((right, bottom), 90), ((right, top), 0)]
    points = [(0, LAP_TOP)]
    for (cx, cy), start in corners:
        for step in range(CORNER_STEPS + 1):
            angle = math.radians(start - 90 * step / CORNER_STEPS)
            points.append((cx + CORNER_RADIUS * math.cos(angle), cy + CORNER_RADIUS * math.sin(angle)))
    points.append((0, LAP_TOP))
    return points


class Lap:
    def __init__(self, points):
        self.points = points
        self.distances = [0.0]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            self.distances.append(self.distances[-1] + math.hypot(x1 - x0, y1 - y0))
        self.length = self.distances[-1]

    def locate(self, distance):
        """Screen position and facing at a distance along the lap."""
        i = min(bisect.bisect_right(self.distances, distance) - 1, len(self.points) - 2)
        (x0, y0), (x1, y1) = self.points[i], self.points[i + 1]
        t = (distance - self.distances[i]) / (self.distances[i + 1] - self.distances[i])
        # Facing comes from rink space, so skating along the leaning end boards
        # uses the straight North/South frames rather than the diagonals.
        return rink_to_screen(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t), facing(x1 - x0, y1 - y0)


def load_skater():
    """For each direction: its skate frames and the pixel row the feet stand on."""
    skater = []
    for name in DIRECTIONS:
        strip = pygame.image.load(SKATE_FRAMES / f"Team_A_T1_PSkate_{name}_strip4.png").convert_alpha()
        height = strip.get_height()
        frames = [strip.subsurface((i * FRAME_WIDTH, 0, FRAME_WIDTH, height))
                  for i in range(strip.get_width() // FRAME_WIDTH)]
        # The South strip is taller than the others, so find the feet from the artwork.
        skater.append((frames, strip.get_bounding_rect().bottom))
    return skater


def draw(screen, rink, skater, lap, distance):
    (x, y), direction = lap.locate(distance)
    frames, feet_y = skater[direction]
    if 0 < distance < lap.length:
        frame = frames[int(distance // STRIDE_LENGTH) % len(frames)]
    else:
        frame = frames[0]
    screen.blit(rink, (0, 0))
    screen.blit(frame, (round(x) - FRAME_WIDTH // 2, round(y) - feet_y))


def main():
    pygame.init()
    rink = pygame.image.load(RINK_IMAGE)
    # SCALED blows the small NES-sized window up by a whole-number factor.
    screen = pygame.display.set_mode(rink.get_size(), pygame.SCALED)
    pygame.display.set_caption("NES Ice Hockey - skating a lap")
    rink = rink.convert()
    skater = load_skater()
    lap = Lap(build_lap())
    clock = pygame.time.Clock()

    elapsed = 0.0
    running = True
    while running:
        elapsed += clock.tick(FPS) / 1000
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                elapsed = 0.0

        distance = min(max(elapsed - START_PAUSE, 0) * SKATE_SPEED, lap.length)
        draw(screen, rink, skater, lap, distance)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
