class RawDatastore:
    def __init__(self) -> None:
        pass


class CatalogService:
    def __init__(self) -> None:
        self.datasets: list[Dataset] = []

    def create_dataset(self, store):
        dataset = Dataset("my_first_dataset")
        self.datasets.append(dataset)


class Dataset:
    def __init__(self, name: str) -> None:
        self.name = name
        self.revision: int = 0

    def get_latest_revision(self) -> int:
        return self.revision


def main():
    print("Running Main")

    store = RawDatastore()
    catalog = CatalogService()
    dataset = catalog.create_dataset(
        store,  # Which store are we creating a new dataset
    )

    dataset.get_latest_revision()


if __name__ == "__main__":
    main()
