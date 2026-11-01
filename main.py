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

Each lap after the first is, on the toss of a coin, either right round the
rink (an oval) or a figure 8, cutting across the middle through the centre spot
and looping round the east end the other way. Half ice on a figure 8 is the
centre spot, so a shot from there comes from the very centre of the rink.

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
TURN_AHEAD = 8        # skaters face the way the track goes this many pixels ahead, turning into bends early
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
CHASE_GAP = 40        # how close the chaser hangs back behind the carrier until making a move

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
# for every pixel further down the screen. The track is planned in a flat "rink
# space" (x measured in pixels along the middle row of the ice) and skewed onto
# the screen, so the skaters follow the boards at an even distance.
RINK_CENTER_X = 355.5
ICE_MID_Y = 128

# The oval lap is a rounded rectangle in rink space. LAP_HALF_LENGTH puts the
# skaters midway between each goal net and the end boards.
LAP_HALF_LENGTH = 282
LAP_TOP = 56
LAP_BOTTOM = 203
CORNER_RADIUS = 50
CORNER_STEPS = 16     # points on each quarter circle

# A figure 8 lap cuts across the middle of the rink twice, straight through the
# centre faceoff spot, turning this many degrees off the top and bottom straights.
CENTRE_SPOT_Y = 127
EIGHT_TURN = 40
EIGHT_STEALS_TO = 200  # on a figure 8, steals happen on the straights at either end, out to this far from half ice


def half_width(y):
    """Distance on screen row y from the centre line to the end boards."""
    return 231.5 + 0.5 * y


def rink_to_screen(x, y):
    return RINK_CENTER_X + x * half_width(y) / half_width(ICE_MID_Y), y


def facing(dx, dy):
    """Index into DIRECTIONS closest to a movement vector (y pointing down)."""
    angle = math.degrees(math.atan2(-dy, dx))
    return round(angle / 45) % len(DIRECTIONS)


def arc(cx, cy, start, sweep, inside):
    """Rink-space points round a circle of radius CORNER_RADIUS centred on
    (cx, cy), from angle start, sweeping sweep degrees. Screen y points down,
    so a negative sweep goes counter-clockwise on screen. Every point carries
    which side the middle of the rink is on: 1 for the left going forwards,
    -1 for the right."""
    steps = max(round(CORNER_STEPS * abs(sweep) / 90), 1)
    points = []
    for step in range(steps + 1):
        angle = math.radians(start + sweep * step / steps)
        points.append((cx + CORNER_RADIUS * math.cos(angle), cy + CORNER_RADIUS * math.sin(angle), inside))
    return points


def junction(rise):
    """How far from the centre line a figure 8 leaves a straight rise pixels
    above or below the centre spot, turning EIGHT_TURN degrees off it to run
    straight through the spot."""
    turn = math.radians(EIGHT_TURN)
    return CORNER_RADIUS * math.sin(turn) + (rise - CORNER_RADIUS * (1 - math.cos(turn))) / math.tan(turn)


class Piece:
    """A stretch of track through rink-space points, see arc()."""

    def __init__(self, points):
        self.points = points
        self.distances = [0.0]
        for (x0, y0, _), (x1, y1, _) in zip(points, points[1:]):
            self.distances.append(self.distances[-1] + math.hypot(x1 - x0, y1 - y0))
        self.length = self.distances[-1]

    def passes(self, x, y):
        """How far along the piece it goes through rink point (x, y), each time it does."""
        found = []
        for i, ((x0, y0, _), (x1, y1, _)) in enumerate(zip(self.points, self.points[1:])):
            dx, dy = x1 - x0, y1 - y0
            t = ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy)
            if 0 <= t < 1 and math.hypot(x0 + dx * t - x, y0 + dy * t - y) < 1e-6:
                found.append(self.distances[i] + (self.distances[i + 1] - self.distances[i]) * t)
        return found

    def locate(self, distance, inset=0):
        """Screen position and forwards facing at a distance along the piece,
        moved inset pixels in towards the middle of the rink."""
        i = min(max(bisect.bisect_right(self.distances, distance) - 1, 0), len(self.points) - 2)
        (x0, y0, inside0), (x1, y1, inside1) = self.points[i], self.points[i + 1]
        dx, dy = x1 - x0, y1 - y0
        length = self.distances[i + 1] - self.distances[i]
        t = (distance - self.distances[i]) / length
        # Behind the goals, in towards the middle is into the net, so the
        # swing fades out round the corners. It fades across the middle of a
        # figure 8 too, where the middle of the rink changes sides.
        inset *= (inside0 + (inside1 - inside0) * t) * abs(dx) / length
        # A positive inset is to the left going forwards.
        x = x0 + dx * t + inset * dy / length
        y = y0 + dy * t - inset * dx / length
        # Facing comes from rink space, so skating along the leaning end boards
        # uses the straight North/South frames rather than the diagonals.
        return rink_to_screen(x, y), facing(dx, dy)


# Every lap starts on the bottom straight west of half ice, where a figure 8
# leaves it heading east. It goes round the east end and back to the top
# straight west of half ice, either right round the rink counter-clockwise (an
# oval) or as a figure 8: turning left across the middle, clockwise round the
# east end, where the middle of the rink is on the right, and turning right back
# across the middle. Then it goes counter-clockwise round the west end, the same
# every lap, back to the start.
LEFT_CORNERS = -LAP_HALF_LENGTH + CORNER_RADIUS
RIGHT_CORNERS = LAP_HALF_LENGTH - CORNER_RADIUS
TOP_CORNERS = LAP_TOP + CORNER_RADIUS
BOTTOM_CORNERS = LAP_BOTTOM - CORNER_RADIUS
TOP_JUNCTION = junction(CENTRE_SPOT_Y - LAP_TOP)
BOTTOM_JUNCTION = junction(LAP_BOTTOM - CENTRE_SPOT_Y)

WEST_END = Piece([(-TOP_JUNCTION, LAP_TOP, 1)]
                 + arc(LEFT_CORNERS, TOP_CORNERS, 270, -90, 1)
                 + arc(LEFT_CORNERS, BOTTOM_CORNERS, 180, -90, 1)
                 + [(-BOTTOM_JUNCTION, LAP_BOTTOM, 1)])
OVAL = Piece([(-BOTTOM_JUNCTION, LAP_BOTTOM, 1)]
             + arc(RIGHT_CORNERS, BOTTOM_CORNERS, 90, -90, 1)
             + arc(RIGHT_CORNERS, TOP_CORNERS, 0, -90, 1)
             + [(-TOP_JUNCTION, LAP_TOP, 1)])
EIGHT = Piece(arc(-BOTTOM_JUNCTION, BOTTOM_CORNERS, 90, -EIGHT_TURN, 1)
              + arc(TOP_JUNCTION, TOP_CORNERS, 270 - EIGHT_TURN, EIGHT_TURN, -1)
              + arc(RIGHT_CORNERS, TOP_CORNERS, 270, 90, -1)
              + arc(RIGHT_CORNERS, BOTTOM_CORNERS, 0, 90, -1)
              + arc(BOTTOM_JUNCTION, BOTTOM_CORNERS, 90, EIGHT_TURN, -1)
              + arc(-TOP_JUNCTION, TOP_CORNERS, 270 + EIGHT_TURN, -EIGHT_TURN, 1))


class LapKind:
    """A way round the east end, with where a lap of this kind crosses half ice
    going forwards, heading east and then west, and the stretches of the lap on
    each side of the rink, north and south, where steals can happen. Distances
    are from the start of the lap."""

    def __init__(self, piece, half_ice, steals):
        self.piece = piece
        self.half_ice = half_ice
        self.steals = steals


def oval_lap():
    bottom, top = OVAL.passes(0, LAP_BOTTOM) + OVAL.passes(0, LAP_TOP)
    # Steals happen near half ice, clear of the corners, which takes them a
    # little way into the west end on either side.
    return LapKind(OVAL, [bottom, top], {"north": [(top - STEAL_REACH, top + STEAL_REACH)],
                                         "south": [(bottom - STEAL_REACH, bottom + STEAL_REACH)]})


def eight_lap():
    # Steals happen on the straights at either end. After a steal at the east
    # end, the next crossing of half ice heads west, and after one at the west
    # end it heads east, so both teams have somewhere to make the last steal
    # and then be heading for their goal.
    west = EIGHT.length
    north = [(EIGHT.passes(TOP_JUNCTION, LAP_TOP)[0], EIGHT.passes(EIGHT_STEALS_TO, LAP_TOP)[0]),
             (west, west + WEST_END.passes(-EIGHT_STEALS_TO, LAP_TOP)[0])]
    south = [(EIGHT.passes(EIGHT_STEALS_TO, LAP_BOTTOM)[0], EIGHT.passes(BOTTOM_JUNCTION, LAP_BOTTOM)[0]),
             (west + WEST_END.passes(-EIGHT_STEALS_TO, LAP_BOTTOM)[0], west + WEST_END.length)]
    return LapKind(EIGHT, EIGHT.passes(0, CENTRE_SPOT_Y), {"north": north, "south": south})


OVAL_LAP = oval_lap()
EIGHT_LAP = eight_lap()


class Track:
    """The skaters' course, one lap after another, each an oval or a figure 8.

    Distances along it are measured from the top middle of lap 0, where Team A
    starts, forwards being counter-clockwise round the oval. Team B starts at
    the bottom middle of lap 1, so laps 0 and 1 are ovals. Every other lap, on
    either side, is an oval or a figure 8 on the toss of a coin, seeded so the
    same seed always gives the same laps.
    """

    def __init__(self, seed):
        self.seed = seed
        self.kinds = {0: OVAL_LAP, 1: OVAL_LAP}
        self.first = 0  # the first lap laid out so far
        # Where each lap laid out so far starts, and where the last one ends.
        start = -OVAL_LAP.half_ice[1]
        self.starts = [start, start + self.length(0)]

    def kind(self, lap):
        if lap not in self.kinds:
            coin = random.Random(f"{self.seed} {lap}").random()
            self.kinds[lap] = EIGHT_LAP if coin < 0.5 else OVAL_LAP
        return self.kinds[lap]

    def length(self, lap):
        return self.kind(lap).piece.length + WEST_END.length

    def start(self, lap):
        while lap < self.first:
            self.first -= 1
            self.starts.insert(0, self.starts[0] - self.length(self.first))
        while lap >= self.first + len(self.starts) - 1:
            self.starts.append(self.starts[-1] + self.length(self.first + len(self.starts) - 1))
        return self.starts[lap - self.first]

    def lap_at(self, distance):
        lap = self.first + max(bisect.bisect_right(self.starts, distance) - 1, 0)
        while distance < self.start(lap):
            lap -= 1
        while distance >= self.start(lap + 1):
            lap += 1
        return lap

    def locate(self, distance, inset=0):
        """Screen position and forwards facing at a distance along the track,
        moved inset pixels in towards the middle of the rink."""
        lap = self.lap_at(distance)
        along = distance - self.start(lap)
        east = self.kind(lap).piece
        if along < east.length:
            return east.locate(along, inset)
        return WEST_END.locate(along - east.length, inset)

    def half_ice(self, lap):
        """Where a lap crosses half ice going forwards, heading east and then west."""
        return [self.start(lap) + along for along in self.kind(lap).half_ice]

    def steals(self, lap, side):
        """The stretches of a lap on the given side of the rink where steals can happen."""
        start = self.start(lap)
        return [(start + low, start + high) for low, high in self.kind(lap).steals[side]]


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
    steal attempt works, the side of the rink, north or south, of each change of
    possession after that, and a seed for which laps are figure 8s."""
    rng = random.Random(seed)
    starter = "A" if rng.random() < 0.5 else "B"
    first_steal = rng.random() < 0.5
    # The exponential distribution gives any number, not just whole ones, so
    # round it. That keeps the average number of changes close to MEAN_CHANGES.
    changes = round(rng.expovariate(1 / MEAN_CHANGES))
    sides = ["north" if rng.random() < 0.5 else "south" for _ in range(changes)]
    # How many laps a play takes isn't known in advance, so the track tosses a
    # coin for each lap as the skaters reach it, seeded with this.
    laps = rng.getrandbits(32)
    return starter, first_steal, sides, laps


def given_seed():
    """The seed asked for on the command line, if any."""
    text = sys.argv[1] if len(sys.argv) > 1 else ""
    return int(text) if text.isdigit() else None


def describe(outcome):
    starter, first_steal, sides, _ = outcome
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
    """A skater on the track, skating forwards (heading 1) or backwards (heading -1)."""

    def __init__(self, track, strips, shooter, goal, distance, heading):
        self.track = track
        self.strips = strips
        self.shooter = shooter    # shooting frames, facing the goal they shoot at
        self.goal = goal          # where in the net their shot ends up
        self.goal_direction = DIRECTIONS.index("West" if goal[0] < RINK_CENTER_X else "East")
        self.distance = distance  # how far forwards along the track from the top middle of lap 0
        self.heading = heading
        self.state = "waiting"
        self.state_time = 0.0     # seconds since the state last changed
        self.then = None          # state to go into after stopping
        self.set_off = START_PAUSE
        self.speed = 0.0
        self.travelled = 0.0      # total distance skated, which drives the stride animation
        self.inset = 0.0          # how far in from the track towards the middle of the rink
        self.turn_from = None     # direction faced when they started turning on the spot
        self.turned_to = None     # direction faced while turning on the spot, and after turning to shoot
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
        """How far along the track the skater is, counted in the direction they are heading."""
        return self.distance * self.heading

    def position(self, ahead=0):
        return self.track.locate(self.distance + self.heading * ahead, self.inset)[0]

    def direction(self):
        if self.turned_to is not None:
            return self.turned_to
        # Turning in early also keeps the puck, out on the stick, off the
        # boards coming out of the corners.
        _, direction = self.track.locate(self.distance + self.heading * TURN_AHEAD)
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

    def __init__(self, team_a, team_b, outcome):
        starter, self.first_steal, sides, laps = outcome
        self.track = Track(laps)
        # Team A starts at the top middle of the oval going forwards, which is
        # counter-clockwise, and Team B at the bottom middle going backwards,
        # so both start off heading west.
        self.a = Skater(self.track, *team_a, WEST_GOAL, 0, 1)
        self.b = Skater(self.track, *team_b, EAST_GOAL, self.track.half_ice(1)[0], -1)
        self.sides = list(sides)  # side of the rink of each steal still to come
        self.carrier = self.a if starter == "A" else self.b
        self.defender = self.b if starter == "A" else self.a  # until they have gone for the puck
        self.defender.set_off += DEFENDER_START_DELAY
        self.chaser = None
        # Whoever has the puck after the first steal attempt swings round the other.
        self.passer = self.defender if self.first_steal else self.carrier
        # Distances along the track from here on are counted in the direction
        # the carrier is heading, like Skater.progress().
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

    def faces_goal(self, skater, east):
        """Whether a skater heading east, or else west, is heading for the goal they shoot at."""
        return east == (DIRECTIONS[skater.goal_direction] == "East")

    def laps_ahead(self, progress, heading):
        """Laps in the order a skater going this way reaches them, starting with
        the lap before the one they're on."""
        lap = self.track.lap_at(progress * heading) - heading
        while True:
            yield lap
            lap += heading

    def next_half_ice(self, progress, heading):
        """Where a skater going this way next crosses half ice after progress,
        and whether they are heading east there.

        Half ice is the top and bottom middle of an oval lap and the centre
        spot, crossed twice, on a figure 8. Going forwards, every lap crosses
        it heading east and then west.
        """
        for lap in self.laps_ahead(progress, heading):
            crossings = zip(self.track.half_ice(lap), (heading > 0, heading < 0))
            for distance, east in sorted(crossings, key=lambda crossing: crossing[0] * heading):
                if distance * heading > progress:
                    return distance * heading, east

    def steal_stretches(self, side, progress, heading):
        """The stretches on the given side of the rink where steals can happen,
        in the order a skater going this way reaches them from progress on."""
        for lap in self.laps_ahead(progress, heading):
            stretches = [sorted((start * heading, end * heading)) for start, end in self.track.steals(lap, side)]
            for low, high in sorted(stretches):
                if high > progress:
                    yield low, high

    def facing_goal_parts(self, low, high, heading):
        """The parts of a stretch where the chaser, if they take the puck there,
        will be heading for their goal when they next cross half ice, at least
        MIN_CARRY on."""
        while low <= high:
            crossing, east = self.next_half_ice(low, heading)
            if self.faces_goal(self.chaser, east):
                yield low, min(high, crossing - MIN_CARRY)
            low = crossing + MIN_CARRY

    def steal_spot(self, side, start, last):
        """Where the next steal happens.

        It is on the first stretch of the given side of the rink where steals
        can happen, see LapKind, at least MIN_CHASE on from start so the skater
        who has just lost the puck has time to catch up. The last steal is kept
        to where the new carrier will be heading for their goal when they next
        cross half ice, which is where they shoot from.
        """
        heading = self.carrier.heading
        earliest = start + MIN_CHASE
        for low, high in self.steal_stretches(side, start, heading):
            parts = self.facing_goal_parts(low, high, heading) if last else [(low, high)]
            for part_low, part_high in parts:
                if part_high >= max(part_low, earliest):
                    return max(part_low, earliest)

    def plan(self):
        """After a change of possession, or the first attempt at one, work out where
        the next steal happens or, after the last, where the carrier shoots from."""
        start = self.carrier.progress()
        if self.sides:
            side = self.sides.pop(0)
            self.target = self.steal_spot(side, start, last=not self.sides)
            return
        self.target = None
        self.shot_spot, east = self.next_half_ice(start, self.carrier.heading)
        self.turn_to_shoot = not self.faces_goal(self.carrier, east)
        self.fit_touches(self.shot_spot - start)

    def chase_speed(self, skater, delay=0):
        """Top speed a skater needs, setting off from a standstill after delay
        seconds, to catch the carrier just as they reach the next steal. Flat
        out after the last steal."""
        if self.target is None:
            return CHASE_SPEED
        time = (self.target - self.carrier.progress()) / SKATE_SPEED - delay
        distance = self.target - skater.progress()
        # Speeding up to v and holding it covers v * time - v**2 / 2a, so solve for v.
        a = ACCELERATION
        return a * time - math.sqrt(max((a * time) ** 2 - 2 * a * distance, 0))

    def update(self, dt):
        self.time += dt
        self.handoff_time += dt
        puck_before = self.puck_position()
        holder_before = self.holder()

        # The chaser moves first, so they judge how they are doing against the
        # carrier before either has moved this frame.
        first, second = (self.b, self.a) if self.chaser is self.b else (self.a, self.b)
        for skater, other in ((first, second), (second, first)):
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
                    # Crossing the middle of a figure 8, they turn a little to face the goal.
                    step = to_go
                    skater.enter("shooting" if skater.direction() == skater.goal_direction else "turning")
            skater.skate(step)
        elif skater.state == "stopping":
            skater.speed = max(skater.speed - SKATE_SPEED ** 2 / (2 * STOP_DISTANCE) * dt, 0)
            skater.skate(skater.speed * dt)
            if skater.speed == 0:
                skater.enter(skater.then)
        elif skater.state == "turning":
            # The carrier turns to face their goal, anyone else right round to
            # chase, showing each direction on the way. Turning right round, they
            # turn towards the middle of the rink, which is on the left going
            # forwards round an oval.
            count = len(DIRECTIONS)
            if skater is self.carrier:
                target = skater.goal_direction
            else:
                target = (skater.turn_from + count // 2) % count
            turn = (target - skater.turn_from) % count
            way = 1 if turn < count // 2 else -1 if turn > count // 2 else skater.heading
            steps = int(skater.state_time / TURN_STEP_TIME)
            if steps < min(turn, count - turn):
                skater.turned_to = (skater.turn_from + way * steps) % count
            elif skater is self.carrier:
                skater.turned_to = target
                skater.enter("shooting")
            else:
                skater.turned_to = None
                skater.heading = -skater.heading
                skater.enter("recovering")
        elif skater.state == "recovering":
            # Set off after the carrier, from the next frame, before it takes
            # more than going flat out to catch them where the next steal is
            # due, or after a breather. Any time in hand, they hang back.
            if self.chase_speed(skater, delay=dt) >= CHASE_SPEED or skater.state_time >= MAX_WAIT:
                skater.enter("chasing")
        elif skater.state == "chasing":
            skater.speed = min(skater.speed + ACCELERATION * dt, CHASE_SPEED)
            step = skater.speed * dt
            ahead = (other.distance - skater.distance) * skater.heading
            if self.target is not None:
                # Close in and hang back behind the carrier until it's time to
                # make a move, which is when it takes going flat out to draw
                # level with them just as they reach the steal spot.
                to_go = self.target - self.carrier.progress()
                in_time = (self.target - skater.progress()) * SKATE_SPEED / to_go if to_go > 0 else math.inf
                if in_time < CHASE_SPEED:
                    step = max(min(step, ahead - CHASE_GAP), 0)
            elif self.turn_to_shoot and other.state != "skating":
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
    team_a =(load_skater(TEAM_A_SKATE_FRAMES, "A"),
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
        return Game(team_a, team_b, outcome)

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
