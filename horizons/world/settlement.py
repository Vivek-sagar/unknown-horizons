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


from storage import PositiveSizedSlotStorage
from horizons.util import WorldObject, NamedObject
from tradepost import TradePost

class Settlement(TradePost, NamedObject):
	"""The Settlement class describes a settlement and stores all the necessary information
	like name, current inhabitants, lists of tiles and houses, etc belonging to the village."""
	def __init__(self, db, owner):
		"""
		@param owner: Player object that owns the settlement
		"""
		self.db = db
		self.__init(owner)
		super(Settlement, self).__init__()

	def __init(self, owner, tax_setting=1.0):
		self.owner = owner
		self.tax_setting = tax_setting
		self.buildings = []
		self.setup_storage()
		self.ground_map = {} # this is the same as in island.py. it uses hard references to the tiles too
		self.produced_res = {} # dictionary of all resources, produced at this settlement
		self.buildings_by_id = {}
		self.branch_office = None # this is set later in the same tick by the bo itself

	def set_tax_setting(self, tax):
		self.tax_setting = tax

	def _possible_names(self):
		names = self.db("SELECT name FROM data.citynames WHERE for_player = 1")
		return map(lambda x: x[0], names)

	@property
	def inhabitants(self):
		"""Returns number of inhabitants (sum of inhabitants of its buildings)"""
		return sum([building.inhabitants for building in self.buildings])

	@property
	def cumulative_running_costs(self):
		"""Return sum of running costs of all buildings"""
		return sum([building.running_costs for building in self.buildings])

	@property
	def cumulative_taxes(self):
		"""Return sum of all taxes payed in this settlement in 1 tax round"""
		return sum([building.last_tax_payed for building in self.buildings if \
								hasattr(building, 'last_tax_payed')])

	@property
	def balance(self):
		"""Returns sum(income) - sum(expenses) for settlement"""
		return self.cumulative_taxes + self.sell_income \
					 - self.cumulative_running_costs - self.buy_expenses

	def level_upgrade(self, lvl):
		"""Upgrades settlement to a new increment.
		It only delegates the upgrade to its buildings."""
		for building in self.buildings:
			building.level_upgrade(lvl)

	def setup_storage(self):
		self.inventory = PositiveSizedSlotStorage(0)
		self.inventory.add_change_listener(self._changed)

	def save(self, db, islandid):
		super(Settlement, self).save(db)

		db("INSERT INTO settlement (rowid, island, owner, tax_setting) VALUES(?, ?, ?, ?)",
			self.worldid, islandid, self.owner.worldid, self.tax_setting)
		for res, amount in self.produced_res.iteritems():
			db("INSERT INTO settlement_produced_res (settlement, res, amount) VALUES(?, ?, ?)", \
			   self.worldid, res, amount)
		self.inventory.save(db, self.worldid)

	@classmethod
	def load(cls, db, worldid, session):
		self = cls.__new__(cls)

		owner, tax = db("SELECT owner, tax_setting FROM settlement WHERE rowid = ?", worldid)[0]
		self.__init(WorldObject.get_object_by_id(owner), tax)

		# load super here cause basic stuff is just set up now
		super(Settlement, self).load(db, worldid)

		# load all buildings from this settlement
		# the buildings will expand the area of the settlement by adding everything,
		# that is in the radius of the building, to the settlement.
		from horizons.world import load_building
		for building_id, building_type in \
				db("SELECT rowid, type FROM building WHERE location = ?", worldid):
			load_building(session, db, building_type, building_id)

		for res, amount in db("SELECT res, amount FROM settlement_produced_res WHERE settlement = ?", worldid):
			self.produced_res[res] = amount

		# load inventory after buildings, since buildings, specifically storages, determine
		# the size of the settlement's inventory
		self.inventory.load(db, worldid)

		return self

	def get_tiles_in_radius(self, location, radius, include_self):
		"""Returns tiles in radius of location.
		This is a generator.
		@param location: anything that supports get_radius_coordinates (usually Rect).
		@param include_self: bool, whether to include the coordinates in location
		"""
		for coord in location.get_radius_coordinates(radius, include_self):
			try:
				yield self.ground_map[coord]
			except KeyError:
				pass

	def add_building(self, building):
		"""Adds a building to the settlement.
		This does not set building.settlement, it must be set beforehand.
		@see Island.add_building
		"""
		self.buildings.append(building)
		if building.id in self.buildings_by_id:
			self.buildings_by_id[building.id].append(building)
		else:
			self.buildings_by_id[building.id] = [building]
		if hasattr(building, "add_building_production_finished_listener"):
			building.add_building_production_finished_listener(self.settlement_building_production_finished)

	def remove_building(self, building):
		"""Properly removes a building from the settlement"""
		self.buildings.remove(building)
		self.buildings_by_id[building.id].remove(building)
		if hasattr(building, "remove_building_production_finished_listener"):
			building.remove_building_production_finished_listener(self.settlement_building_production_finished)

	def get_buildings_by_id(self, id):
		"""Returns all buildings on this island that have the given id"""
		if id in self.buildings_by_id.keys():
			return self.buildings_by_id[id]
		else:
			return []

	def settlement_building_production_finished(self, building, produced_res):
		"""Callback function for registering the production of resources."""
		for res, amount in produced_res.iteritems():
			if res in self.produced_res:
				self.produced_res[res] += amount
			else:
				self.produced_res[res] = amount

