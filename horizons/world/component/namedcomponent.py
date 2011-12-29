# ###################################################
# Copyright (C) 2011 The Unknown Horizons Team
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

from horizons.world.component import Component
from horizons.util.changelistener import ChangeListener


class NamedComponent(Component):
	"""An object that has a special name. "Special" means, that it's not (only) autogenerated."""

	NAME = "namedcomponent"

	names_used = []

	def __init__(self, name=None):
		super(NamedComponent, self).__init__()
		self.name = name

	def initialize(self):
		self.set_name(self.name)

	def set_name(self, name=None):
		"""Actually sets the name."""
		if self.name is not None and self.name in NamedComponent.names_used:
			NamedComponent.names_used.remove(self.name)
		if name is None:
			name = self.get_default_name()
		self.name = name
		NamedComponent.names_used.append(self.name)
		if isinstance(self.instance, ChangeListener):
			self.instance._changed()

	def _possible_names(self):
		return ['object_%s' % self.instance.worldid]

	def get_default_name(self):
		newname = newnametmp = self.instance.session.random.choice(self._possible_names())
		index = 2
		while newname in NamedComponent.names_used:
			newname = "%s %s" % (newnametmp, index)
			index += 1
		return newname

	def save(self, db):
		super(NamedComponent, self).save(db)
		db("INSERT INTO name (rowid, name) VALUES(?, ?)", self.instance.worldid, self.name)

	def load(self, db, worldid):
		super(NamedComponent, self).load(db, worldid)
		self.name = None
		name = db("SELECT name FROM name WHERE rowid = ?", worldid)[0][0]
		# We need unicode strings as the name is displayed on screen.
		self.set_name(unicode(name, 'utf-8'))

	@classmethod
	def reset(cls):
		cls.names_used = []

class ShipNameComponent(NamedComponent):

	def _possible_names(self):
		names = self.instance.session.db("SELECT name FROM shipnames WHERE for_player = 1")
		# We need unicode strings as the name is displayed on screen.
		return map(lambda x: unicode(x[0], 'utf-8'), names)


class PirateShipNameComponent(NamedComponent):

	def _possible_names(self):
		names = self.instance.session.db("SELECT name FROM shipnames WHERE for_pirate = 1")
		return map(lambda x: unicode(x[0]), names)

class SettlementNameComponent(NamedComponent):

	def _possible_names(self):
		names = self.instance.session.db("SELECT name FROM citynames WHERE for_player = 1")
		return map(lambda x: x[0], names)