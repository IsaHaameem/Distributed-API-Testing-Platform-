"""Environment variable data-access layer."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.environment_variable import EnvironmentVariable


class EnvironmentVariableRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, variable_id: UUID) -> EnvironmentVariable | None:
        result = await self.session.execute(
            select(EnvironmentVariable).where(EnvironmentVariable.id == variable_id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: UUID) -> list[EnvironmentVariable]:
        result = await self.session.execute(
            select(EnvironmentVariable)
            .where(EnvironmentVariable.project_id == project_id)
            .order_by(EnvironmentVariable.key)
        )
        return list(result.scalars().all())

    async def create(
        self, *, project_id: UUID, key: str, value: str, is_secret: bool
    ) -> EnvironmentVariable:
        variable = EnvironmentVariable(
            project_id=project_id, key=key, value=value, is_secret=is_secret
        )
        self.session.add(variable)
        await self.session.flush()
        await self.session.refresh(variable)
        return variable

    async def update(self, variable: EnvironmentVariable, **fields) -> EnvironmentVariable:
        for field_name, value in fields.items():
            setattr(variable, field_name, value)
        await self.session.flush()
        await self.session.refresh(variable)
        return variable

    async def delete(self, variable: EnvironmentVariable) -> None:
        await self.session.delete(variable)
        await self.session.flush()