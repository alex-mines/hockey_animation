"""Example animation: two skaters fight for the puck, differently every time.

A Team A (Type 1) skater starts at the top middle of the ice and a Team B
(Type 1) skater at the bottom middle, both facing west. Each play is drawn at
random:

- which team starts with the puck (a coin flip),
- whether the other team's first steal attempt works (a coin flip), which
  decides who is chasing whom,
- how many times the puck changes hands after that (exponential with an
  average of 3, rounded to a whole number), and
- whether each of those steals happens on the north or the south side of the
  rink (a coin flip each).

The skater with the puck dribbles it round the rink and the other comes to
meet them head on and goes for it. Whoever comes away without the puck stops,
turns round and gives chase, catching up to steal it on the side of the rink
that was drawn, and the skater who loses it chases in turn. After the last
change of possession, the carrier shoots the next time they reach half ice:
Team A on the west goal, Team B on the east goal.

Every play comes from a seed, so the same seed always plays out the same way.
Each play is seeded with the time it starts, printed with what was drawn; run
`uv run main.py 42` to watch seed 42 instead. Press SPACE to play again (the
same seed if one was given, otherwise a new one), ESC to quit.

It also runs in a web browser: pygbag builds it into a web page (see
web/index.html).
"""
import asyncio
import bisect
import math
import random
import sys
import time
from pathlib import Path

import pygame

ASSETS = Path(__file__).parent / "NES_Ice_Hockey_Full_Files" / "NES Ice Hockey Full Files"
RINK_IMAGE = ASSETS / "Ice Hockey Rink Tile Set" / "NES_IceHockey_IceRink_WithGoal.png"
TEAM_A_SKATE_FRAMES = ASSETS / "Team A Type 1" / "Skate Frames"
TEAM_A_SHOOT_FRAMES = ASSETS / "Team A Type 1" / "Shoot Frames"
TEAM_B_SKATE_FRAMES = ASSETS / "Team B Type 1" / "Skate Frames"
TEAM_B_SHOOT_FRAMES = ASSETS / "Team B Type 1" / "Shoot"

FPS = 60
SKATE_SPEED = 100     # pixels per second
STRIDE_LENGTH = 12    # pixels travelled per animation frame
TURN_AHEAD = 8        # skaters face the way the lap goes this many pixels ahead, turning into bends early
START_PAUSE = 1.0     # seconds to stand still before setting off
DRIBBLE_LENGTH = 48   # pixels skated between touches of the puck
DRIBBLE_REACH = 10    # furthest the puck gets ahead of the stick, in pixels
WINDUP_TIME = 0.4     # seconds holding the stick up before the swing
SWING_TIME = 0.08     # seconds on the downswing frame before the puck is struck
PUCK_SPEED = 360      # pixels per second once shot

# Setting off together, the two skaters would meet head on behind the west
# goal, where there is no room to get past each other. Whoever starts without
# the puck waits a little so they meet on open ice in the west half instead.
DEFENDER_START_DELAY = 2.5  # seconds after the skater with the puck sets off
STEAL_GAP = 28        # how far apart the skaters are when the defender's stick reaches the puck
HANDOFF_TIME = 0.12   # seconds for the puck to slide onto a new stick or blade position
PASS_WIDTH = 16       # how far a skater swings towards the middle of the rink to get round the other
PASS_RANGE = 40       # they swing out over this distance either side of the other skater
STOP_DISTANCE = 12    # pixels a skater slides while stopping from skating speed
TURN_STEP_TIME = 0.08 # seconds on each direction frame while turning round
CHASE_SPEED = 120     # top speed chasing the puck, faster than carrying it so the chaser catches up
ACCELERATION = 250    # pixels per second per second, setting off on the chase
CHASE_GAP = 40        # closest the chaser gets behind the carrier once there are no steals left

# The random play, and where on the ice its steals happen.
MEAN_CHANGES = 3      # average number of changes of possession after the first steal attempt
MIN_CHASE = 450       # pixels the carrier skates, at least, from one steal to the next
MAX_WAIT = 0.75       # seconds a skater who has lost the puck stands, at most, before chasing
STEAL_REACH = 160     # steals happen within this many pixels of half ice, clear of the corners
MIN_CARRY = 60        # pixels the last carrier skates, at least, before shooting

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

# Inside each goal's net, just behind the goal line. Team A shoots on the west
# goal and Team B on the east goal.
WEST_GOAL = (99, 122)
EAST_GOAL = (612, 122)

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
        distance %= self.length
        i = min(bisect.bisect_right(self.distances, distance) - 1, len(self.points) - 2)
        (x0, y0), (x1, y1) = self.points[i], self.points[i + 1]
        dx, dy = x1 - x0, y1 - y0
        length = self.distances[i + 1] - self.distances[i]
        t = (distance - self.distances[i]) / length
        # Behind the goals, in towards the middle is into the net, so the
        # swing fades out round the corners.
        inset *= abs(dx) / length
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
    South strip. Mirrored frames face the other way.
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


def draw_outcome(seed):
    """Draw how a play goes: which team starts with the puck, whether the first
    steal attempt works, and the side of the rink, north or south, of each
    change of possession after that."""
    rng = random.Random(seed)
    starter = "A" if rng.random() < 0.5 else "B"
    first_steal = rng.random() < 0.5
    # The exponential distribution gives any number, not just whole ones, so
    # round it. That keeps the average number of changes close to MEAN_CHANGES.
    changes = round(rng.expovariate(1 / MEAN_CHANGES))
    sides = ["north" if rng.random() < 0.5 else "south" for _ in range(changes)]
    return starter, first_steal, sides


def given_seed():
    """The seed asked for on the command line, if any."""
    text = sys.argv[1] if len(sys.argv) > 1 else ""
    return int(text) if text.isdigit() else None


def describe(outcome):
    starter, first_steal, sides = outcome
    other = {"A": "B", "B": "A"}
    holder = other[starter] if first_steal else starter
    if len(sides) % 2:
        holder = other[holder]
    if not sides:
        changes = "After that the puck doesn't change hands."
    else:
        times = "once" if len(sides) == 1 else f"{len(sides)} times"
        changes = f"After that it changes hands {times}: {', '.join(sides)}."
    return (f"Team {starter} starts with the puck. Team {other[starter]}'s first steal attempt "
            f"{'works' if first_steal else 'misses'}.\n{changes}\n"
            f"Team {holder} shoots on the {'west' if holder == 'A' else 'east'} goal.")


class Skater:
    """A skater on the lap, skating counter-clockwise (heading 1) or clockwise (heading -1)."""

    def __init__(self, lap, strips, shooter, goal, distance, heading):
        self.lap = lap
        self.strips = strips
        self.shooter = shooter    # shooting frames, facing the goal they shoot at
        self.goal = goal          # where in the net their shot ends up
        self.distance = distance  # how far counter-clockwise round the lap from the top middle
        self.heading = heading
        self.state = "waiting"
        self.state_time = 0.0     # seconds since the state last changed
        self.then = None          # state to go into after stopping
        self.set_off = START_PAUSE
        self.speed = 0.0
        self.top_speed = CHASE_SPEED
        self.travelled = 0.0      # total distance skated, which drives the stride animation
        self.inset = 0.0          # how far in from the lap towards the middle of the rink
        self.turn_from = None     # direction faced when they started turning round on the spot
        self.turned_to = None     # direction faced while turning round on the spot
        self.shot_frame = None    # frame of the shooter strip shown while shooting

    def enter(self, state, then=None):
        self.state = state
        self.state_time = 0.0
        self.then = then
        if state == "turning":
            self.turn_from = self.direction()
        elif state == "shooting":
            self.shot_frame = 0

    def skate(self, step):
        self.distance += self.heading * step
        self.travelled += step

    def progress(self):
        """How far round the lap the skater is, counted in the direction they are heading."""
        return self.distance * self.heading

    def position(self, ahead=0):
        return self.lap.locate(self.distance + self.heading * ahead, self.inset)[0]

    def direction(self):
        if self.turned_to is not None:
            return self.turned_to
        # Turning in early also keeps the puck, out on the stick, off the
        # boards coming out of the corners.
        _, direction = self.lap.locate(self.distance + self.heading * TURN_AHEAD)
        return direction if self.heading > 0 else (direction + 4) % len(DIRECTIONS)

    def image(self):
        """The frame to show, the middle of its helmet and the row its feet stand on."""
        if self.shot_frame is not None:
            frames, helmet_x, feet_y = self.shooter
            return frames[self.shot_frame], helmet_x, feet_y
        frames, helmet_x, feet_y = self.strips[self.direction()]
        return frames[int(self.travelled // STRIDE_LENGTH) % len(frames)], helmet_x, feet_y


class Game:
    """One play, set up from an outcome made by draw_outcome()."""

    def __init__(self, lap, team_a, team_b, outcome):
        self.lap = lap
        # Team A goes round counter-clockwise from the top middle and Team B
        # clockwise from the bottom middle, so both start off heading west.
        self.a = Skater(lap, *team_a, WEST_GOAL, 0, 1)
        self.b = Skater(lap, *team_b, EAST_GOAL, lap.length / 2, -1)
        starter, self.first_steal, sides = outcome
        self.sides = list(sides)  # side of the rink of each steal still to come
        self.carrier = self.a if starter == "A" else self.b
        self.defender = self.b if starter == "A" else self.a  # until they have gone for the puck
        self.defender.set_off += DEFENDER_START_DELAY
        self.chaser = None
        # Whoever has the puck after the first steal attempt swings round the other.
        self.passer = self.defender if self.first_steal else self.carrier
        # Distances round the lap from here on are counted in the direction the
        # carrier is heading, like Skater.progress().
        self.target = None          # where the next steal happens
        self.shot_spot = None       # where the last carrier shoots from
        self.turn_to_shoot = False  # whether they get there skating away from their goal
        self.time = 0.0
        # How far the carrier had skated when they got the puck and how far
        # they skate between touches.
        self.dribble_from = 0.0
        self.touch_length = DRIBBLE_LENGTH
        self.handoff_from = None
        self.handoff_time = HANDOFF_TIME
        self.shot_from = self.shot_target = self.struck_at = None

    def phase(self):
        """How far through the current touch of the puck the carrier is, from 0 to 1."""
        return (self.carrier.travelled - self.dribble_from) / self.touch_length % 1

    def lead(self):
        """How far the puck has run ahead of the carrier's stick.

        Each touch pushes the puck ahead faster than the skater, then it slows
        down steadily until the skater catches it on the stick again.
        """
        phase = self.phase()
        return 4 * DRIBBLE_REACH * phase * (1 - phase)

    def take_puck(self, skater):
        self.carrier = skater
        self.dribble_from = skater.travelled
        self.touch_length = DRIBBLE_LENGTH

    def fit_touches(self, remaining):
        """Fit a whole number of touches into the rest of the carry, so the puck is
        back on the stick when the carrier stops, without moving it now."""
        phase = self.phase()
        touches = max(round(remaining / DRIBBLE_LENGTH + phase), 1)
        self.touch_length = remaining / (touches - phase)
        self.dribble_from = self.carrier.travelled - phase * self.touch_length

    def faces_goal(self, skater, side, heading):
        """Whether a skater going round this way faces the goal they shoot at when
        crossing half ice on this side. Counter-clockwise is west along the north side."""
        west = (side == "north") == (heading > 0)
        return west == (skater.goal[0] < RINK_CENTER_X)

    def steal_spot(self, side, start, last):
        """Where the next steal happens.

        It is on the given side of the rink, near enough half ice to be clear of
        the corners, and at least MIN_CHASE on from start so the skater who has
        just lost the puck has time to catch up. The last steal is kept to the
        side of half ice that has the new carrier facing their goal when they
        next cross half ice, which is where they shoot from.
        """
        length = self.lap.length
        middle = 0 if side == "north" else length / 2
        low, high = -STEAL_REACH, STEAL_REACH
        if last:
            if self.faces_goal(self.chaser, side, self.carrier.heading):
                high = -MIN_CARRY
            else:
                low = MIN_CARRY
        earliest = start + MIN_CHASE
        # The first time round that this side's stretch ends past the earliest point.
        middle += math.ceil((earliest - high - middle) / length) * length
        return max(middle + low, earliest)

    def plan(self):
        """After a change of possession, or the first attempt at one, work out where
        the next steal happens or, after the last, where the carrier shoots from."""
        start = self.carrier.progress()
        if self.sides:
            side = self.sides.pop(0)
            self.target = self.steal_spot(side, start, last=not self.sides)
            return
        self.target = None
        # Half ice comes round every half lap, at the top middle and the bottom middle.
        half = self.lap.length / 2
        halves = math.floor(start / half) + 1
        self.shot_spot = halves * half
        side = "north" if halves % 2 == 0 else "south"
        self.turn_to_shoot = not self.faces_goal(self.carrier, side, self.carrier.heading)
        self.fit_touches(self.shot_spot - start)

    def chase_speed(self, skater):
        """Top speed a skater needs, setting off now from a standstill, to catch the
        carrier just as they reach the next steal. Flat out after the last steal."""
        if self.target is None:
            return CHASE_SPEED
        time = (self.target - self.carrier.progress()) / SKATE_SPEED
        distance = self.target - skater.progress()
        # Speeding up to v and holding it covers v * time - v**2 / 2a, so solve for v.
        a = ACCELERATION
        return a * time - math.sqrt(max((a * time) ** 2 - 2 * a * distance, 0))

    def update(self, dt):
        self.time += dt
        self.handoff_time += dt
        puck_before = self.puck_position()
        holder_before = self.holder()

        for skater, other in ((self.a, self.b), (self.b, self.a)):
            self.move(skater, other, dt)
        self.contest()
        self.swing()

        # When the puck is stolen, or its carrier turns and their blade moves,
        # the puck slides across to its new place on the stick.
        if self.carrier is not None and self.holder() != holder_before:
            self.handoff_from = puck_before
            self.handoff_time = 0.0

    def move(self, skater, other, dt):
        skater.state_time += dt
        if skater.state == "waiting":
            if self.time > skater.set_off:
                skater.enter("skating")
        elif skater.state == "skating":
            skater.speed = SKATE_SPEED
            step = skater.speed * dt
            if skater is self.carrier and self.shot_spot is not None:
                to_go = self.shot_spot - skater.progress()
                if self.turn_to_shoot and to_go - step <= STOP_DISTANCE:
                    # Skating away from their goal, so stop on half ice and turn round.
                    skater.enter("stopping", then="turning")
                elif step >= to_go:
                    step = to_go
                    skater.enter("shooting")
            skater.skate(step)
        elif skater.state == "stopping":
            skater.speed = max(skater.speed - SKATE_SPEED ** 2 / (2 * STOP_DISTANCE) * dt, 0)
            skater.skate(skater.speed * dt)
            if skater.speed == 0:
                skater.enter(skater.then)
        elif skater.state == "turning":
            # Turn towards the middle of the rink, which is on the skater's
            # left going counter-clockwise, showing each direction on the way.
            steps = int(skater.state_time / TURN_STEP_TIME)
            if steps < len(DIRECTIONS) // 2:
                skater.turned_to = (skater.turn_from + skater.heading * steps) % len(DIRECTIONS)
            else:
                skater.turned_to = None
                skater.heading = -skater.heading
                # The carrier has turned to face their goal, anyone else to chase.
                skater.enter("shooting" if skater is self.carrier else "recovering")
        elif skater.state == "recovering":
            # Set off after the carrier in time to catch them where the next
            # steal is due: flat out, or after a breather, a little slower.
            speed = self.chase_speed(skater)
            if speed >= CHASE_SPEED or skater.state_time >= MAX_WAIT:
                skater.top_speed = min(speed, CHASE_SPEED)
                skater.enter("chasing")
        elif skater.state == "chasing":
            skater.speed = min(skater.speed + ACCELERATION * dt, skater.top_speed)
            step = skater.speed * dt
            ahead = (other.distance - skater.distance) * skater.heading
            if self.target is None:
                if self.turn_to_shoot and other.state != "skating":
                    # The shooter has stopped to turn round, so skate on past them.
                    if ahead <= -PASS_RANGE:
                        skater.enter("stopping", then="standing")
                else:
                    # No steals left: close in, but leave the carrier room to shoot.
                    step = max(min(step, ahead - CHASE_GAP), 0)
            skater.skate(step)
        elif skater.state == "shooting":
            if skater.state_time < WINDUP_TIME:
                skater.shot_frame = 0
            elif skater.state_time < WINDUP_TIME + SWING_TIME:
                skater.shot_frame = 1
            else:
                skater.shot_frame = 2
                if self.carrier is skater:
                    self.shot_from = self.puck_position()
                    self.shot_target = skater.goal
                    self.struck_at = self.time
                    self.carrier = None

    def contest(self):
        """The defender going for the puck head on, then the chaser catching the carrier."""
        carrier, chaser = self.carrier, self.chaser
        if carrier is None:
            return
        if self.defender is not None:
            ahead = (self.defender.distance - carrier.distance) * carrier.heading
            if ahead <= STEAL_GAP + self.lead():
                # The defender's stick reaches the puck. Whoever comes away
                # without it slides to a stop and turns round to chase.
                loser = carrier if self.first_steal else self.defender
                if self.first_steal:
                    self.take_puck(self.defender)
                loser.enter("stopping", then="turning")
                self.chaser, self.defender = loser, None
                self.plan()
        elif self.target is not None and chaser.state == "chasing" and chaser.progress() >= carrier.progress():
            # The chaser draws level on the inside and takes the puck.
            self.take_puck(chaser)
            chaser.enter("skating")
            carrier.enter("stopping", then="recovering")
            self.chaser = carrier
            self.plan()

    def swing(self):
        """Whoever is getting round the other swings in towards the middle of the rink."""
        gap = abs(self.b.distance - self.a.distance)
        if self.chaser is not None and gap >= PASS_RANGE:
            # Once the two are clear of each other, the chaser is next to get round.
            self.passer = self.chaser
        for skater in (self.a, self.b):
            if skater is self.passer and gap < PASS_RANGE:
                skater.inset = PASS_WIDTH * (1 + math.cos(math.pi * gap / PASS_RANGE)) / 2
            else:
                skater.inset = 0

    def holder(self):
        """Who has the puck and which way they face, which sets where the blade is."""
        return self.carrier and (self.carrier, self.carrier.direction())

    def puck_position(self):
        if self.carrier is not None:
            x, y = self.carrier.position(ahead=self.lead())
            stick_x, stick_y = PUCK_ON_STICK[self.carrier.direction()]
            x, y = x + stick_x, y + stick_y
            if self.handoff_time < HANDOFF_TIME:
                from_x, from_y = self.handoff_from
                t = self.handoff_time / HANDOFF_TIME
                x, y = from_x + (x - from_x) * t, from_y + (y - from_y) * t
            return x, y
        # Shot: the puck flies in a straight line from the stick and stops in the net.
        from_x, from_y = self.shot_from
        target_x, target_y = self.shot_target
        flight = (self.time - self.struck_at) * PUCK_SPEED
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


async def main():
    pygame.init()
    rink = pygame.image.load(RINK_IMAGE)
    # SCALED blows the small NES-sized window up by a whole-number factor.
    screen = pygame.display.set_mode(rink.get_size(), pygame.SCALED)
    pygame.display.set_caption("NES Ice Hockey - steal and shoot")
    rink = rink.convert()
    lap = Lap(build_lap())
    team_a = (load_skater(TEAM_A_SKATE_FRAMES, "A"),
              load_strip(TEAM_A_SHOOT_FRAMES / "Team_A_T1_Shoot_West_strip3.png", 3))
    # Team B's East shooting strip in the pack is a copy of the West one, so
    # mirror the West one instead.
    team_b = (load_skater(TEAM_B_SKATE_FRAMES, "B"),
              load_strip(TEAM_B_SHOOT_FRAMES / "Team_B_T1_Shoot_West_strip3.png", 3, mirror=True))
    puck = make_puck()
    clock = pygame.time.Clock()
    seed = given_seed()

    def play():
        # Without a seed from the command line, use the time it starts, in milliseconds.
        play_seed = seed if seed is not None else time.time_ns() // 1_000_000
        outcome = draw_outcome(play_seed)
        print(f"Seed {play_seed}. {describe(outcome)}", end="\n\n")
        return Game(lap, team_a, team_b, outcome)

    game = play()
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
                game = play()

        game.update(dt)
        game.draw(screen, rink, puck)
        pygame.display.flip()
        # In a web browser, nothing is shown until Python hands control back.
        await asyncio.sleep(0)

    pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())
