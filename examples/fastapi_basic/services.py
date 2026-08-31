import uuid

from atlasboxpy_controller import AlreadyExistsError, NotFoundError
from atlasboxpy_controller.fastapi_integration import extract_patch_data

from .exceptions import UsernameReservedError
from .models import CreateUserRequest, UpdateUserRequest, UserOut

_RESERVED_NAMES = {"admin", "root"}


class UserService:
    """Fake in-memory repository + business logic, standing in for a real
    database-backed service. What matters for this example is that it
    raises atlasboxpy_controller's DomainError subclasses — it doesn't know or
    care that a gateway or an HTTP route exists."""

    def __init__(self) -> None:
        self._users: dict[str, dict] = {}

    async def create_user(self, payload: CreateUserRequest) -> UserOut:
        if payload.name.lower() in _RESERVED_NAMES:
            raise UsernameReservedError(f"{payload.name!r} is a reserved username")
        if any(u["email"] == payload.email for u in self._users.values()):
            raise AlreadyExistsError(f"A user with email {payload.email} already exists")
        user_id = str(uuid.uuid4())
        user = {"id": user_id, "name": payload.name, "email": payload.email}
        self._users[user_id] = user
        return UserOut(**user)

    async def get_user(self, user_id: str) -> UserOut:
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return UserOut(**user)

    async def list_users(self) -> list[UserOut]:
        return [UserOut(**user) for user in self._users.values()]

    async def update_user(self, user_id: str, payload: UpdateUserRequest) -> UserOut:
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        user.update(extract_patch_data(payload))
        return UserOut(**user)

    async def delete_user(self, user_id: str) -> None:
        if user_id not in self._users:
            raise NotFoundError(f"User {user_id} not found")
        del self._users[user_id]
