from validator_gateway import BaseController

from .models import CreateUserRequest, UpdateUserRequest, UserOut
from .services import UserService


class UserController(BaseController):
    def __init__(self, service: UserService) -> None:
        super().__init__()
        self.service = service

    async def create_user(self, payload: CreateUserRequest) -> UserOut:
        return await self.service.create_user(payload)

    async def get_user(self, user_id: str) -> UserOut:
        return await self.service.get_user(user_id)

    async def list_users(self) -> list[UserOut]:
        return await self.service.list_users()

    async def update_user(self, user_id: str, payload: UpdateUserRequest) -> UserOut:
        return await self.service.update_user(user_id, payload)

    async def delete_user(self, user_id: str) -> None:
        await self.service.delete_user(user_id)
