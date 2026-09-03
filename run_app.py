from app.__main__ import main
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
