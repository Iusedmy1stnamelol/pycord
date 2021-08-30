"""
The MIT License (MIT)

Copyright (c) 2015-present Rapptz

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import OrderedDict

from .enums import SlashCommandOptionType
from .interactions import Interaction
from .utils import cached_property
from .member import Member
from .user import User


class SlashCommand:
    type = 1

    def __new__(cls, *args, **kwargs):
        self = super().__new__(cls)

        self.__original_kwargs__ = kwargs.copy()
        return self

    def __init__(self, func, *args, **kwargs):
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("Callback must be a coroutine.")
        self.callback = func

        self.guild_ids = kwargs.get("guild_ids", None)

        name = kwargs.get("name") or func.__name__
        if not isinstance(name, str):
            raise TypeError("Name of a command must be a string.")
        self.name = name

        description = kwargs.get("description") or (
            inspect.cleandoc(func.__doc__) if func.__doc__ is not None else None
        )
        if description is None:
            raise ValueError(
                "Description of a command is required and cannot be empty."
            )

        if not isinstance(description, str):
            raise TypeError("Description of a command must be a string.")
        self.description = description

        options = OrderedDict(inspect.signature(func).parameters)
        options.pop(list(options)[0])
        self.options = []
        for a, o in options.items():
            o = o.annotation
            if o.name is None:
                o.name = a
            self.options.append(o)
        self.is_subcommand = False    

    def to_dict(self):
        as_dict = {
            "name": self.name,
            "description": self.description,
            "options": [o.to_dict() for o in self.options],
        }
        if self.is_subcommand:
            as_dict["type"] = SlashCommandOptionType.sub_command.value

        return as_dict

    def __eq__(self, other):
        return (
            isinstance(other, SlashCommand)
            and other.name == self.name
            and other.description == self.description
        )

    async def invoke(self, interaction):
        args = (o['value'] for o in interaction.data.get('options', []))
        ctx = InteractionContext(interaction)
        await self.callback(ctx, *args)

class Option:
    def __init__(self, input_type, /, description, **kwargs):
        self.name = kwargs.pop("name", None)
        self.description = description
        if not isinstance(input_type, SlashCommandOptionType):
            input_type = SlashCommandOptionType.from_datatype(input_type)
        self.input_type = input_type
        self.required = kwargs.pop("required", True)
        self.choices = [
            o if isinstance(o, OptionChoice) else OptionChoice(o)
            for o in kwargs.pop("choices", list())
        ]

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "type": self.input_type.value,
            "required": self.required,
            "choices": [c.to_dict() for c in self.choices],
        }

class SubCommandGroup(Option):
    type = 1
    def __init__(self, name, description, guild_ids = None, parent_group=None):
        super().__init__(
            SlashCommandOptionType.sub_command_group, 
            name=name,
            description=description,
        )
        self.subcommands = []
        self.guild_ids = guild_ids
        self.parent_group = parent_group

    def to_dict(self):
        as_dict =  {
            "name": self.name,
            "description": self.description,
            "options": [c.to_dict() for c in self.subcommands],
        }

        if self.parent_group is not None:
            as_dict["type"] = self.input_type.value

        return as_dict

    def command(self, **kwargs):
        def wrap(func) -> SlashCommand:
            command = SlashCommand(func, **kwargs)
            command.is_subcommand = True
            self.subcommands.append(command)
            return command

        return wrap

    def command_group(self, name, description):
        if self.parent_group is not None:
            raise Exception('Subcommands can only be nested once') # TODO: Improve this

        sub_command_group = SubCommandGroup(name, description, parent_group=self)
        self.subcommands.append(sub_command_group)
        return sub_command_group
       
    async def invoke(self, interaction):
        option = interaction.data["options"][0]
        # command can be SubCommandGroup or SlashCommand
        # but we don't need to worry about that
        command = list(filter(lambda x: x.name == option["name"], self.subcommands))[0]
        interaction.data = option
        return await command.invoke(interaction)
        
class OptionChoice:
    def __init__(self, name, value=None):
        self.name = name
        self.value = value or name

    def to_dict(self):
        return {"name": self.name, "value": self.value}

class UserCommand:
    type = 2

    def __new__(cls, *args, **kwargs):
        self = super().__new__(cls)

        self.__original_kwargs__ = kwargs.copy()
        return self

    def __init__(self, func, *args, **kwargs):
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("Callback must be a coroutine.")
        self.callback = func

        self.guild_ids = kwargs.get("guild_ids", None)

        self.description = ""
        self.name = kwargs.pop("name", func.__name__)
        if not isinstance(self.name, str):
            raise TypeError("Name of a command must be a string.")

    def to_dict(self):
        return {
            "name":self.name,
            "description":self.description,
            "type":self.type
        }

    async def invoke(self, interaction):
        if "members" not in interaction.data["resolved"]:
            _data = interaction.data["resolved"]["users"]
            for i, v in _data.items():
                v["id"] = int(i)
                user = v
            target = User(state=interaction._state, data=user)
        else:
            _data = interaction.data["resolved"]["members"]
            for i, v in _data.items():
                v["id"] = int(i)
                member = v
            _data = interaction.data["resolved"]["users"]
            for i, v in _data.items():
                v["id"] = int(i)
                user = v
            member["user"] = user
            target = Member(data=member, guild=interaction._state._get_guild(interaction.guild_id), state=interaction._state)
        ctx = InteractionContext(interaction)
        await self.callback(ctx, target)

class MessageCommand:
    type = 3


class InteractionContext:
    def __init__(self, interaction: Interaction):
        self.interaction = interaction

    @cached_property
    def channel(self):
        return self.interaction.channel

    @cached_property
    def channel_id(self):
        return self.interaction.channel_id

    @cached_property
    def guild(self):
        return self.interaction.guild

    @cached_property
    def guild_id(self):
        return self.interaction.guild_id

    @cached_property
    def message(self):
        return self.interaction.message

    @cached_property
    def user(self):
        return self.interaction.user

    @property
    def respond(self):
        return self.interaction.response.send_message

    @property
    def edit(self):
        return self.interaction.response.edit_message
