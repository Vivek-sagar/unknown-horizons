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

from horizons.command.unit import Act
from horizons.gui.mousetools.buildingtool import BuildingTool 
from horizons.gui.mousetools.cursortool import CursorTool
from tests.gui import gui_test
from tests.gui.helper import get_player_ship


@gui_test(use_dev_map=True, timeout=60)
def test_found_settlement(gui):
	"""
	Found a settlement.
	"""
	player = gui.session.world.player
	target = (68, 10)
	gui.session.view.center(*target)

	assert len(player.settlements) == 0

	ship = get_player_ship(gui.session)
	Act(ship, *target)(player)

	# wait until ship arrives
	while (ship.position.x, ship.position.y) != target:
		gui.run()

	gui.select([ship])
	gui.trigger('overview_trade_ship', 'found_settlement/action/default')

	assert isinstance(gui.cursor, BuildingTool)
	gui.cursor_move(64, 12)
	gui.cursor_click(64, 12, 'left')

	assert isinstance(gui.cursor, CursorTool)
	assert len(player.settlements) == 1
