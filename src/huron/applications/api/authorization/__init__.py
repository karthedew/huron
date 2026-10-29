"""Authentication of requests by Huron token."""

from huron.applications.api.authorization.actors import ActorDep, current_actor

__all__ = ["ActorDep", "current_actor"]
