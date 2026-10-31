"""Example animation: a Team B skater steals the puck from a Team A skater.

A Team A (Type 1) skater starts at the top middle of the ice and dribbles the
puck counter-clockwise: left along the top boards, down behind the west goal
and along the bottom. A Team B (Type 1) skater starts at the bottom middle and
skates clockwise to meet them, steals the puck and carries it on round the
rink, behind the west goal and back along the top, while the Team A skater
turns round and gives chase. Half a lap from where they started, at half ice,
the Team B skater shoots the puck into the east goal.

Press SPACE to play it again, ESC to quit.
"""
import bisect
import math
from pathlib import Path

import pygame

ASSETS = Path(__file__).parent / "NES_Ice_Hockey_Full_Files" / "NES Ice Hockey Full Files"
RINK_IMAGE = ASSETS / "Ice Hockey Rink Tile Set" / "NES_IceHockey_IceRink_WithGoal.png"
TEAM_A_SKATE_FRAMES = ASSETS / "Team A Type 1" / "Skate Frames"
TEAM_B_SKATE_FRAMES = ASSETS / "Team B Type 1" / "Skate Frames"
TEAM_B_SHOOT_FRAMES = ASSETS / "Team B Type 1" / "Shoot"

FPS = 60
SKATE_SPEED = 100     # pixels per second
STRIDE_LENGTH = 12    # pixels travelled per animation frame
START_PAUSE = 1.0     # seconds to stand still before setting off
DRIBBLE_LENGTH = 48   # pixels skated between touches of the puck
DRIBBLE_REACH = 10    # furthest the puck gets ahead of the stick, in pixels
WINDUP_TIME = 0.4     # seconds holding the stick up before the swing
SWING_TIME = 0.08     # seconds on the downswing frame before the puck is struck
PUCK_SPEED = 360      # pixels per second once shot

# Setting off together, the two skaters would meet head on behind the west
# goal, where there is no room to get past each other. Team B waits a little
# so they meet on open ice at the bottom left instead.
TEAM_B_START_DELAY = 2.5  # seconds after Team A sets off
STEAL_GAP = 28        # how far apart the skaters are when Team B's stick reaches the puck
PASS_WIDTH = 16       # how far Team B swings towards the middle of the rink to get round Team A
PASS_RANGE = 40       # Team B swings out over this distance either side of Team A
STOP_DISTANCE = 12    # pixels Team A slides while stopping after losing the puck
TURN_STEP_TIME = 0.08 # seconds on each direction frame while turning round
CHASE_SPEED = 115     # Team A skates a little faster when chasing
ACCELERATION = 250    # pixels per second per second, setting off on the chase
CHASE_GAP = 40        # closest Team A gets behind Team B

# Compass names in order of angle / 45 degrees (0 = east, counter-clockwise),
# matching the Team_?_T1_PSkate_<Direction>_strip4.png file names.
DIRECTIONS = ["East", "NorthEast", "North", "NorthWest", "West", "SouthWest", "South", "SouthEast"]

# Where the puck sits relative to the skater's helmet and feet for each
# direction above, just ahead of the stick blade in that direction's frames.
PUCK_ON_STICK = [(16, -2), (11, -6), (6, -8), (-12, -7), (-16, -2), (-11, 1), (-1, 2), (10, 1)]

# There is no puck in the asset pack, so it is drawn from this pixel pattern.
PUCK_PIXELS = [".##.",
               "####",
               ".##."]

# Inside the east goal's net, just behind the goal line.
SHOT_TARGET = (612, 122)

# The rink is drawn in perspective: the end boards lean outwards by half a pixel
# for every pixel further down the screen. The lap is planned in a flat "rink
# space" (x measured in pixels along the middle row of the ice) and skewed onto
# the screen, so the skaters follow the boards at an even distance.
RINK_CENTER_X = 355.5
ICE_MID_Y = 128

# The lap is a rounded rectangle in rink space. LAP_HALF_LENGTH puts the
# skaters midway between each goal net and the end boards.
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

    def locate(self, distance, inset=0):
        """Screen position and counter-clockwise facing at a distance along the lap,
        moved inset pixels in towards the middle of the rink."""
        i = min(max(bisect.bisect_right(self.distances, distance) - 1, 0), len(self.points) - 2)
        (x0, y0), (x1, y1) = self.points[i], self.points[i + 1]
        dx, dy = x1 - x0, y1 - y0
        length = self.distances[i + 1] - self.distances[i]
        t = (distance - self.distances[i]) / length
        # Skating counter-clockwise, the middle of the rink is on the left.
        x = x0 + dx * t + inset * dy / length
        y = y0 + dy * t - inset * dx / length
        # Facing comes from rink space, so skating along the leaning end boards
        # uses the straight North/South frames rather than the diagonals.
        return rink_to_screen(x, y), facing(dx, dy)


def load_strip(path, count, mirror=False):
    """A strip's frames, the middle of the helmet and the pixel row the feet stand on.

    Frames are lined up on the helmet so the body stays put when the skater
    changes direction, and stood on the feet, which are lower in the taller
    South strip.
    """
    strip = pygame.image.load(path).convert_alpha()
    width = strip.get_width() // count
    frames = [strip.subsurface((i * width, 0, width, strip.get_height())) for i in range(count)]
    if mirror:
        frames = [pygame.transform.flip(frame, True, False) for frame in frames]
    top = frames[0].get_bounding_rect().top
    helmet = [x for x in range(width) if frames[0].get_at((x, top)).a]
    return frames, (helmet[0] + helmet[-1]) // 2, strip.get_bounding_rect().bottom


def load_skater(folder, team):
    return [load_strip(folder / f"Team_{team}_T1_PSkate_{name}_strip4.png", 4) for name in DIRECTIONS]


def make_puck():
    puck = pygame.Surface((len(PUCK_PIXELS[0]), len(PUCK_PIXELS)), pygame.SRCALPHA)
    for y, row in enumerate(PUCK_PIXELS):
        for x, pixel in enumerate(row):
            if pixel == "#":
                puck.set_at((x, y), (0, 0, 0))
    return puck


class Skater:
    """A skater on the lap, skating counter-clockwise (heading 1) or clockwise (heading -1)."""

    def __init__(self, lap, strips, distance, heading, shooter=None):
        self.lap = lap
        self.strips = strips
        self.shooter = shooter
        self.distance = distance  # how far counter-clockwise round the lap from the top middle
        self.heading = heading
        self.speed = 0.0
        self.travelled = 0.0      # total distance skated, which drives the stride animation
        self.inset = 0.0          # how far in from the lap towards the middle of the rink
        self.turned_to = None     # direction faced while turning round on the spot
        self.shot_frame = None    # frame of the shooter strip shown while shooting

    def skate(self, step):
        self.distance += self.heading * step
        self.travelled += step

    def position(self, ahead=0):
        return self.lap.locate(self.distance + self.heading * ahead, self.inset)[0]

    def direction(self):
        if self.turned_to is not None:
            return self.turned_to
        _, direction = self.lap.locate(self.distance)
        return direction if self.heading > 0 else (direction + 4) % len(DIRECTIONS)

    def image(self):
        """The frame to show, the middle of its helmet and the row its feet stand on."""
        if self.shot_frame is not None:
            frames, helmet_x, feet_y = self.shooter
            return frames[self.shot_frame], helmet_x, feet_y
        frames, helmet_x, feet_y = self.strips[self.direction()]
        return frames[int(self.travelled // STRIDE_LENGTH) % len(frames)], helmet_x, feet_y


class Game:
    def __init__(self, lap, team_a, team_b, team_b_shooter):
        self.lap = lap
        self.a = Skater(lap, team_a, 0, 1)
        self.b = Skater(lap, team_b, lap.length / 2, -1, team_b_shooter)
        self.time = 0.0
        self.a_state = "skating"
        self.turn_time = 0.0
        self.turn_from = None
        self.shot_time = None
        self.shot_from = None
        # Whoever has the puck, how far they had skated when they got it and
        # how far they skate between touches.
        self.carrier = self.a
        self.dribble_from = 0.0
        self.touch_length = DRIBBLE_LENGTH

    def lead(self):
        """How far the puck has run ahead of the carrier's stick.

        Each touch pushes the puck ahead faster than the skater, then it slows
        down steadily until the skater catches it on the stick again.
        """
        phase = (self.carrier.travelled - self.dribble_from) / self.touch_length % 1
        return 4 * DRIBBLE_REACH * phase * (1 - phase)

    def update(self, dt):
        self.time += dt
        a, b = self.a, self.b

        # Team B waits, then skates clockwise to the top middle, half a lap
        # from the bottom middle, and shoots for the east goal from there.
        if self.shot_time is not None:
            self.shot_time += dt
            if self.shot_time < WINDUP_TIME:
                b.shot_frame = 0
            elif self.shot_time < WINDUP_TIME + SWING_TIME:
                b.shot_frame = 1
            else:
                b.shot_frame = 2
                if self.carrier is b:
                    self.shot_from = self.puck_position()
                    self.carrier = None
        elif self.time > START_PAUSE + TEAM_B_START_DELAY:
            b.skate(min(SKATE_SPEED * dt, b.distance))
            if b.distance == 0:
                self.shot_time = 0.0
                b.shot_frame = 0

        # Team A dribbles counter-clockwise until the puck is stolen, slides to
        # a stop, turns round and chases Team B.
        if self.a_state == "skating":
            if self.time > START_PAUSE:
                a.speed = SKATE_SPEED
                a.skate(a.speed * dt)
        elif self.a_state == "stopping":
            a.speed = max(a.speed - SKATE_SPEED ** 2 / (2 * STOP_DISTANCE) * dt, 0)
            a.skate(a.speed * dt)
            if a.speed == 0:
                self.a_state = "turning"
                self.turn_from = a.direction()
        elif self.a_state == "turning":
            # Turn towards the middle of the rink, which is on the skater's
            # left going counter-clockwise, showing each direction on the way.
            self.turn_time += dt
            steps = int(self.turn_time / TURN_STEP_TIME)
            if steps < len(DIRECTIONS) // 2:
                a.turned_to = (self.turn_from + a.heading * steps) % len(DIRECTIONS)
            else:
                a.turned_to = None
                a.heading = -a.heading
                self.a_state = "chasing"
        elif self.a_state == "chasing":
            a.speed = min(a.speed + ACCELERATION * dt, CHASE_SPEED)
            room = a.distance - b.distance - CHASE_GAP
            a.skate(max(min(a.speed * dt, room), 0))

        # Team B steals the puck when their stick reaches it, then swings
        # towards the middle of the rink to get round Team A.
        if self.carrier is a and b.distance - a.distance <= STEAL_GAP + self.lead():
            self.carrier = b
            self.dribble_from = b.travelled
            # A whole number of touches fit before the shot, so the puck is
            # back on the stick when Team B stops to shoot.
            self.touch_length = b.distance / max(round(b.distance / DRIBBLE_LENGTH), 1)
            self.a_state = "stopping"
        if self.carrier is b:
            gap = b.distance - a.distance
            if abs(gap) < PASS_RANGE:
                b.inset = PASS_WIDTH * (1 + math.cos(math.pi * gap / PASS_RANGE)) / 2
            else:
                b.inset = 0

    def puck_position(self):
        if self.carrier is not None:
            x, y = self.carrier.position(ahead=self.lead())
            stick_x, stick_y = PUCK_ON_STICK[self.carrier.direction()]
            return x + stick_x, y + stick_y
        # Shot: the puck flies in a straight line from the stick and stops in the net.
        from_x, from_y = self.shot_from
        target_x, target_y = SHOT_TARGET
        flight = (self.shot_time - WINDUP_TIME - SWING_TIME) * PUCK_SPEED
        t = min(flight / math.hypot(target_x - from_x, target_y - from_y), 1)
        return from_x + (target_x - from_x) * t, from_y + (target_y - from_y) * t

    def draw(self, screen, rink, puck):
        sprites = []
        for skater in (self.a, self.b):
            frame, helmet_x, feet_y = skater.image()
            x, y = skater.position()
            sprites.append((y, frame, (round(x) - helmet_x, round(y) - feet_y)))
        puck_x, puck_y = self.puck_position()
        sprites.append((puck_y, puck, (round(puck_x) - puck.get_width() // 2,
                                       round(puck_y) - puck.get_height() // 2)))
        screen.blit(rink, (0, 0))
        # Whatever is further up the ice is further away, so it is drawn first.
        for _, image, position in sorted(sprites, key=lambda sprite: sprite[0]):
            screen.blit(image, position)


def main():
    pygame.init()
    rink = pygame.image.load(RINK_IMAGE)
    # SCALED blows the small NES-sized window up by a whole-number factor.
    screen = pygame.display.set_mode(rink.get_size(), pygame.SCALED)
    pygame.display.set_caption("NES Ice Hockey - steal and shoot")
    rink = rink.convert()
    lap = Lap(build_lap())
    team_a = load_skater(TEAM_A_SKATE_FRAMES, "A")
    team_b = load_skater(TEAM_B_SKATE_FRAMES, "B")
    # The pack's Team_B_T1_Shoot_East_strip3.png is a copy of the West strip,
    # so Team B's east-facing shot is the West strip mirrored.
    team_b_shooter = load_strip(TEAM_B_SHOOT_FRAMES / "Team_B_T1_Shoot_West_strip3.png", 3, mirror=True)
    puck = make_puck()
    clock = pygame.time.Clock()

    game = Game(lap, team_a, team_b, team_b_shooter)
    running = True
    while running:
        # Cap the step so dragging the window doesn't make the skaters jump.
        dt = min(clock.tick(FPS) / 1000, 0.05)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                game = Game(lap, team_a, team_b, team_b_shooter)

        game.update(dt)
        game.draw(screen, rink, puck)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
