"""Example animation: a Team A (Type 1) skater does a lap of the rink with the puck.

The skater starts at the top middle of the ice and skates counter-clockwise:
left along the top boards, down behind the left goal, along the bottom boards,
up behind the right goal and back to where it started. From there, at the
halfway line, the skater shoots the puck into the west (left) goal.

Press SPACE to play it again, ESC to quit.
"""
import bisect
import math
from pathlib import Path

import pygame

ASSETS = Path(__file__).parent / "NES_Ice_Hockey_Full_Files" / "NES Ice Hockey Full Files"
RINK_IMAGE = ASSETS / "Ice Hockey Rink Tile Set" / "NES_IceHockey_IceRink_WithGoal.png"
SKATE_FRAMES = ASSETS / "Team A Type 1" / "Skate Frames"
SHOOT_FRAMES = ASSETS / "Team A Type 1" / "Shoot Frames"

FPS = 60
SKATE_SPEED = 100     # pixels per second
STRIDE_LENGTH = 12    # pixels travelled per animation frame
START_PAUSE = 1.0     # seconds to stand still before setting off
DRIBBLE_LENGTH = 48   # pixels skated between touches of the puck
DRIBBLE_REACH = 10    # furthest the puck gets ahead of the stick, in pixels
WINDUP_TIME = 0.4     # seconds holding the stick up before the swing
SWING_TIME = 0.08     # seconds on the downswing frame before the puck is struck
PUCK_SPEED = 360      # pixels per second once shot

# Compass names in order of angle / 45 degrees (0 = east, counter-clockwise),
# matching the Team_A_T1_PSkate_<Direction>_strip4.png file names.
DIRECTIONS = ["East", "NorthEast", "North", "NorthWest", "West", "SouthWest", "South", "SouthEast"]

# Where the puck sits relative to the skater's feet for each direction above,
# just ahead of the stick blade in that direction's skate frames.
PUCK_ON_STICK = [(15, -2), (14, -6), (4, -8), (-16, -7), (-16, -2), (-10, 1), (-1, 2), (8, 1)]

# There is no puck in the asset pack, so it is drawn from this pixel pattern.
PUCK_PIXELS = [".##.",
               "####",
               ".##."]

# Inside the west goal's net, just behind the goal line.
SHOT_TARGET = (99, 122)

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


def load_strip(path, count):
    """A strip's frames and the pixel row the feet stand on."""
    strip = pygame.image.load(path).convert_alpha()
    width = strip.get_width() // count
    frames = [strip.subsurface((i * width, 0, width, strip.get_height())) for i in range(count)]
    # The South strip is taller than the others, so find the feet from the artwork.
    return frames, strip.get_bounding_rect().bottom


def make_puck():
    puck = pygame.Surface((len(PUCK_PIXELS[0]), len(PUCK_PIXELS)), pygame.SRCALPHA)
    for y, row in enumerate(PUCK_PIXELS):
        for x, pixel in enumerate(row):
            if pixel == "#":
                puck.set_at((x, y), (0, 0, 0))
    return puck


def draw(screen, rink, skater, shooter, puck, lap, elapsed):
    distance = min(max(elapsed - START_PAUSE, 0) * SKATE_SPEED, lap.length)
    (x, y), direction = lap.locate(distance)
    frames, feet_y = skater[direction]
    stick_x, stick_y = PUCK_ON_STICK[direction]
    # Dribbling: each touch pushes the puck ahead faster than the skater, then
    # it slows down steadily until the skater catches it on the stick again.
    # A whole number of touches fit in the lap, so the puck is back on the
    # stick when the skater stops. The puck runs ahead along the lap itself so
    # it follows the boards round the corners.
    touches = round(lap.length / DRIBBLE_LENGTH)
    phase = distance * touches / lap.length % 1
    lead = 4 * DRIBBLE_REACH * phase * (1 - phase)
    (ahead_x, ahead_y), _ = lap.locate(distance + lead)
    puck_x, puck_y = ahead_x + stick_x, ahead_y + stick_y

    shot_time = elapsed - START_PAUSE - lap.length / SKATE_SPEED
    if shot_time < 0:
        frame = frames[int(distance // STRIDE_LENGTH) % len(frames)] if distance > 0 else frames[0]
    else:
        frames, feet_y = shooter
        if shot_time < WINDUP_TIME:
            frame = frames[0]
        elif shot_time < WINDUP_TIME + SWING_TIME:
            frame = frames[1]
        else:
            frame = frames[2]
            # The puck flies in a straight line from the stick and stops in the net.
            flight = (shot_time - WINDUP_TIME - SWING_TIME) * PUCK_SPEED
            target_x, target_y = SHOT_TARGET
            t = min(flight / math.hypot(target_x - puck_x, target_y - puck_y), 1)
            puck_x, puck_y = puck_x + (target_x - puck_x) * t, puck_y + (target_y - puck_y) * t

    # Whichever is further up the ice is further away, so it is drawn first.
    sprites = [(y, frame, (round(x) - frame.get_width() // 2, round(y) - feet_y)),
               (puck_y, puck, (round(puck_x) - puck.get_width() // 2, round(puck_y) - puck.get_height() // 2))]
    screen.blit(rink, (0, 0))
    for _, image, position in sorted(sprites, key=lambda sprite: sprite[0]):
        screen.blit(image, position)


def main():
    pygame.init()
    rink = pygame.image.load(RINK_IMAGE)
    # SCALED blows the small NES-sized window up by a whole-number factor.
    screen = pygame.display.set_mode(rink.get_size(), pygame.SCALED)
    pygame.display.set_caption("NES Ice Hockey - skating a lap")
    rink = rink.convert()
    skater = [load_strip(SKATE_FRAMES / f"Team_A_T1_PSkate_{name}_strip4.png", 4) for name in DIRECTIONS]
    lap = Lap(build_lap())
    # Shoot facing the goal from where the lap ends.
    (end_x, end_y), _ = lap.locate(lap.length)
    shot_direction = DIRECTIONS[facing(SHOT_TARGET[0] - end_x, SHOT_TARGET[1] - end_y)]
    shooter = load_strip(SHOOT_FRAMES / f"Team_A_T1_Shoot_{shot_direction}_strip3.png", 3)
    puck = make_puck()
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

        draw(screen, rink, skater, shooter, puck, lap, elapsed)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
