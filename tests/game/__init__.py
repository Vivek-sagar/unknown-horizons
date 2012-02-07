# ###################################################
# Copyright (C) 2012 The Unknown Horizons Team
# team@unknown-horizons.org
# This file is part of Unknown Horizons.
#
# Unknown Horizons is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the
# Free Software Foundation, Inc.,
# 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
# ###################################################


import contextlib
import inspect
import os
import signal
import tempfile
from functools import wraps

import mock

# check if SIGALRM is supported, this is not the case on Windows
# we might provide an alternative later, but for now, this will do
try:
	from signal import SIGALRM
	TEST_TIMELIMIT = True
except ImportError:
	TEST_TIMELIMIT = False

import horizons.main
import horizons.world	# needs to be imported before session
from horizons.ai.aiplayer import AIPlayer
from horizons.command.building import Build
from horizons.command.unit import CreateUnit
from horizons.constants import GROUND, UNITS, BUILDINGS, RES
from horizons.ext.dummy import Dummy
from horizons.extscheduler import ExtScheduler
from horizons.scheduler import Scheduler
from horizons.spsession import SPSession
from horizons.util import Color, DbReader, Rect, SavegameAccessor, Point, DifficultySettings
from horizons.util.uhdbaccessor import read_savegame_template
from horizons.world.component.storagecomponent import StorageComponent

from tests import RANDOM_SEED


db = None

def setup_package():
	"""
	Setup read-only database. This might have to change in the future, tests should not
	fail only because a production now takes 1 second more in the game.
	"""
	global db
	db = horizons.main._create_main_db()
	ExtScheduler.create_instance(Dummy)


def create_map():
	"""
	Create a map with a square island (20x20) at position (20, 20) and return the path
	to the database file.
	"""

	# Create island.
	fd, islandfile = tempfile.mkstemp()
	os.close(fd)

	db = DbReader(islandfile)
	db("CREATE TABLE ground(x INTEGER NOT NULL, y INTEGER NOT NULL, ground_id INTEGER NOT NULL, action_id TEXT NOT NULL, rotation INTEGER NOT NULL)")
	db("CREATE TABLE island_properties(name TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)")

	db("BEGIN TRANSACTION")
	tiles = []
	for x, y in Rect.init_from_topleft_and_size(0, 0, 20, 20).tuple_iter():
		if (0 < x < 20) and (0 < y < 20):
			ground = GROUND.DEFAULT_LAND
		else:
			# Add coastline at the borders.
			ground = GROUND.SHALLOW_WATER
		tiles.append([x, y] + list(ground))
	db.execute_many("INSERT INTO ground VALUES(?, ?, ?, ?, ?)", tiles)
	db("COMMIT")

	# Create savegame with the island above.
	fd, savegame = tempfile.mkstemp()
	os.close(fd)

	db = DbReader(savegame)
	read_savegame_template(db)
	db("BEGIN TRANSACTION")
	db("INSERT INTO island (x, y, file) VALUES(?, ?, ?)", 20, 20, islandfile)
	db("COMMIT")

	return savegame


@contextlib.contextmanager
def _dbreader_convert_dummy_objects():
	"""
	Wrapper around DbReader.__call__ to convert Dummy objects to valid values.

	This is needed because some classes attempt to store Dummy objects in the
	database, e.g. ConcreteObject with self._instance.getActionRuntime().
	We fix this by replacing it with zero, SQLite doesn't care much about types,
	and hopefully a number is less likely to break code than None.

	Yes, this is ugly and will most likely break later. For now, it works.
	"""
	def deco(func):
		@wraps(func)
		def wrapper(self, command, *args):
			args = list(args)
			for i in range(len(args)):
				if args[i].__class__.__name__ == 'Dummy':
					args[i] = 0
			return func(self, command, *args)
		return wrapper

	original = DbReader.__call__
	DbReader.__call__ = deco(DbReader.__call__)
	yield
	DbReader.__call__ = original


class SPTestSession(SPSession):

	def __init__(self, db, rng_seed=None):
		super(SPTestSession, self).__init__(Dummy(), db, rng_seed)
		self.reset_autosave = Dummy()

	def save(self, *args, **kwargs):
		"""
		Wrapper around original save function to fix some things.
		"""
		# SavegameManager.write_metadata tries to create a screenshot and breaks when
		# accessing fife properties
		with mock.patch('horizons.spsession.SavegameManager'):
			# We need to covert Dummy() objects to a sensible value that can be stored
			# in the database
			with _dbreader_convert_dummy_objects():
				return super(SPTestSession, self).save(*args, **kwargs)

	def load(self, savegame, players):
		self.savegame = savegame
		super(SPTestSession, self).load(savegame, players, False, False, 0)

	def end(self, keep_map=False):
		"""
		Clean up temporary files.
		"""
		super(SPTestSession, self).end()

		# Find all islands in the map first
		savegame_db = SavegameAccessor(self.savegame)
		if not keep_map:
			for (island_file, ) in savegame_db('SELECT file FROM island'):
				if not island_file.startswith('random:'): # random islands don't exist as files
					os.remove(island_file)
		# Finally remove savegame
		savegame_db.close()
		os.remove(self.savegame)

	@classmethod
	def cleanup(cls):
		"""
		If a test uses manual session management, we cannot be sure that session.end was
		called before a crash, leaving the game in an unclean state. This method should
		return the game to a valid state.
		"""
		Scheduler.destroy_instance()

	def run(self, ticks=1, seconds=None):
		"""
		Run the scheduler the given count of ticks or (in-game) seconds. Default is 1 tick,
		if seconds are passed, they will overwrite the tick count.
		"""
		if seconds:
			ticks = self.timer.get_ticks(seconds)

		for i in range(ticks):
			Scheduler().tick( Scheduler().cur_tick + 1 )


def new_session(mapgen=create_map, rng_seed=RANDOM_SEED, human_player = True, ai_players = 0):
	"""
	Create a new session with a map, add one human player and a trader (it will crash
	otherwise). It returns both session and player to avoid making the function-baed
	tests too verbose.
	"""
	session = SPTestSession(horizons.main.db, rng_seed=rng_seed)
	human_difficulty = DifficultySettings.DEFAULT_LEVEL
	ai_difficulty = DifficultySettings.EASY_LEVEL

	players = []
	if human_player:
		players.append({'id': 1, 'name': 'foobar', 'color': Color[1], 'local': True, 'ai': False, 'difficulty': human_difficulty})
	for i in xrange(ai_players):
		id = i + human_player + 1
		players.append({'id': id, 'name': ('AI' + str(i)), 'color': Color[id], 'local': id == 1, 'ai': True, 'difficulty': ai_difficulty})

	session.load(mapgen(), players)

	if ai_players > 0: # currently only ai tests use the ships
		for player in session.world.players:
			point = session.world.get_random_possible_ship_position()
			ship = CreateUnit(player.worldid, UNITS.PLAYER_SHIP_CLASS, point.x, point.y)(issuer=player)
			# give ship basic resources
			for res, amount in session.db("SELECT resource, amount FROM start_resources"):
				ship.get_component(StorageComponent).inventory.alter(res, amount)
		AIPlayer.load_abstract_buildings(session.db)

	return session, session.world.player


def load_session(savegame, rng_seed=RANDOM_SEED):
	"""
	Start a new session with the given savegame.
	"""
	session = SPTestSession(horizons.main.db, rng_seed=rng_seed)

	session.load(savegame, [])

	return session


def new_settlement(session, pos=Point(30, 20)):
	"""
	Creates a settlement at the given position. It returns the settlement and the island
	where it was created on, to avoid making function-baed tests too verbose.
	"""
	island = session.world.get_island(pos)
	assert island, "No island found at %s" % pos
	player = session.world.player

	ship = CreateUnit(player.worldid, UNITS.PLAYER_SHIP_CLASS, pos.x, pos.y)(player)
	for res, amount in session.db("SELECT resource, amount FROM start_resources"):
		ship.get_component(StorageComponent).inventory.alter(res, amount)

	building = Build(BUILDINGS.WAREHOUSE_CLASS, pos.x, pos.y, island, ship=ship)(player)
	assert building, "Could not build warehouse at %s" % pos

	return (building.settlement, island)


def game_test(*args, **kwargs):
	"""
	Decorator that is needed for each test in this package. setup/teardown of function
	based tests can't pass arguments to the test, or keep a reference somewhere.
	If a test fails, we need to reset the session under all circumstances, otherwise we
	break the rest of the tests. The global database reference has to be set each time too,
	unittests use this too, and we can't predict the order tests run (we should not rely
	on it anyway).

	The decorator can be used in 2 ways:

		1. No decorator arguments

			@game_test
			def foo(session, player):
				pass

		2. Pass extra arguments (timeout, different map generator)

			@game_test(timeout=10, mapgen=my_map_generator)
			def foo(session, player):
				pass
	"""
	no_decorator_arguments = len(args) == 1 and not kwargs and inspect.isfunction(args[0])

	timeout = kwargs.get('timeout', 15 * 60)	# zero means no timeout, 15min default
	mapgen = kwargs.get('mapgen', create_map)
	human_player = kwargs.get('human_player', True)
	ai_players = kwargs.get('ai_players', 0)
	manual_session = kwargs.get('manual_session', False)

	if TEST_TIMELIMIT and timeout:
		def handler(signum, frame):
			raise Exception('Test run exceeded %ds time limit' % timeout)
		signal.signal(signal.SIGALRM, handler)

	def deco(func):
		@wraps(func)
		def wrapped(*args):
			horizons.main.db = db
			if not manual_session:
				s, p = new_session(mapgen = mapgen, human_player = human_player, ai_players = ai_players)
			if TEST_TIMELIMIT and timeout:
				signal.alarm(timeout)
			try:
				if not manual_session:
					return func(s, p, *args)
				else:
					return func(*args)
			finally:
				if not manual_session:
					s.end()
				else:
					SPTestSession.cleanup()

				if TEST_TIMELIMIT and timeout:
					signal.alarm(0)
		return wrapped

	if no_decorator_arguments:
		# return the wrapped function
		return deco(args[0])
	else:
		# return a decorator
		return deco

game_test.__test__ = False


def settle(s):
	"""
	Create a new settlement, start with some resources.
	"""
	settlement, island = new_settlement(s)
	settlement.get_component(StorageComponent).inventory.alter(RES.GOLD_ID, 5000)
	settlement.get_component(StorageComponent).inventory.alter(RES.BOARDS_ID, 50)
	settlement.get_component(StorageComponent).inventory.alter(RES.TOOLS_ID, 50)
	settlement.get_component(StorageComponent).inventory.alter(RES.BRICKS_ID, 50)
	return settlement, island


def set_trace():
	"""
	Use this function instead of directly importing if from pdb. The test run
	time limit will be disabled and stdout restored (so the debugger actually
	works).
	"""
	if TEST_TIMELIMIT:
		signal.alarm(0)

	from nose.tools import set_trace
	set_trace()


_multiprocess_can_split_ = True
