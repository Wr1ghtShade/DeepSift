# deepsift-sdk

What every DeepSift service is built on. It implements [`docs/specs/service-contract.md`](../docs/specs/service-contract.md).

| Module | Content |
|---|---|
| `entities` | Entity types, the `Entity` model, value normalization and identity keys |
| `manifest` | The `Manifest` model and `load_manifest()` |
| `messages` | `Task`, `Event`, error codes |
| `service` | `Service` base class, `TaskContext`, `ServiceError` |
| `runner` | `execute()`: runs one task and turns the outcome into contract events |
| `bus` | `RedisBus` (Redis Streams) and `MemoryBus` (tests) |
| `worker` | `serve()` and `python -m deepsift_sdk.worker module:Class` for containers |
| `local` | `LocalRun` and `discover()`: local mode used by the CLI |
| `confidence` | Noisy-OR combination and High / Medium / Low levels |
| `detect` | Guesses a selector's type |

## Writing a service

```python
from deepsift_sdk import Entity, EntityType, Service, Task, TaskContext


class ExampleService(Service):
    async def run(self, task: Task, ctx: TaskContext) -> None:
        url = f"https://example.org/{task.input.value}"
        await ctx.found(Entity(type=EntityType.PROFILE, value=url, confidence=0.5))
```

Put a `manifest.yaml` next to the module, and declare the class as an entry point in the `deepsift.services` group so the CLI finds it. `services/sherlock/` is the reference example.
