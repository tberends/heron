"""
This module provides functionality to split LAS files into smaller chunks based on spatial bounds.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import laspy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def recursive_split(
    x_min: float,
    y_min: float,
    x_max: float,
    y_max: float,
    max_x_size: float,
    max_y_size: float,
) -> List[Tuple[float, float, float, float]]:
    """
    Recursively splits a bounding box into smaller chunks based on maximum size.

    Parameters:
        x_min (float): Minimum x-coordinate of the bounding box
        y_min (float): Minimum y-coordinate of the bounding box
        x_max (float): Maximum x-coordinate of the bounding box
        y_max (float): Maximum y-coordinate of the bounding box
        max_x_size (float): Maximum allowed size in x-direction
        max_y_size (float): Maximum allowed size in y-direction

    Returns:
        List[Tuple[float, float, float, float]]: List of bounding boxes (x_min, y_min, x_max, y_max)
    """
    x_size = x_max - x_min
    y_size = y_max - y_min

    if x_size > max_x_size:
        left = recursive_split(
            x_min, y_min, x_min + (x_size // 2), y_max, max_x_size, max_y_size
        )
        right = recursive_split(
            x_min + (x_size // 2), y_min, x_max, y_max, max_x_size, max_y_size
        )
        return left + right
    elif y_size > max_y_size:
        up = recursive_split(
            x_min, y_min, x_max, y_min + (y_size // 2), max_x_size, max_y_size
        )
        down = recursive_split(
            x_min, y_min + (y_size // 2), x_max, y_max, max_x_size, max_y_size
        )
        return up + down
    else:
        return [(x_min, y_min, x_max, y_max)]


def tuple_size(string: str) -> Tuple[float, float]:
    """
    Converts a string in the format 'numberxnumber' to a tuple of floats.

    Parameters:
        string (str): String in the format 'numberxnumber' (e.g., '50.0x65.14')

    Returns:
        Tuple[float, float]: Tuple containing the two numbers

    Raises:
        ValueError: If the string is not in the correct format
    """
    try:
        return tuple(map(float, string.split("x")))
    except:
        raise ValueError("Size must be in the form of numberxnumber eg: 50.0x65.14")


def split_las_file(
    input_file: str,
    output_dir: str,
    size: Tuple[float, float],
    points_per_iter: int = 10**6,
) -> None:
    """
    Splits a LAS file into smaller chunks based on spatial bounds.

    Parameters:
        input_file (str): Path to the input LAS file
        output_dir (str): Directory to save the output chunks
        size (Tuple[float, float]): Maximum size of each chunk (width, height)
        points_per_iter (int): Number of points to process in each iteration
    """
    with laspy.open(input_file) as file:
        sub_bounds = recursive_split(
            file.header.x_min,
            file.header.y_min,
            file.header.x_max,
            file.header.y_max,
            size[0],
            size[1],
        )

        writers: List[Optional[laspy.LasWriter]] = [None] * len(sub_bounds)
        try:
            count = 0
            for points in file.chunk_iterator(points_per_iter):
                logger.info(f"Progress: {count / file.header.point_count * 100}%")

                # For performance we need to use copy
                # so that the underlying arrays are contiguous
                x, y = points.x.copy(), points.y.copy()

                point_piped = 0

                for i, (x_min, y_min, x_max, y_max) in enumerate(sub_bounds):
                    mask = (x >= x_min) & (x <= x_max) & (y >= y_min) & (y <= y_max)

                    if np.any(mask):
                        if writers[i] is None:
                            # Make output file path based on input file and inputfile extension
                            output_path = Path(output_dir) / f"{Path(input_file).stem}_{round(x_min)}_{round(y_max)}.las"
                            writers[i] = laspy.open(
                                output_path, mode="w", header=file.header
                            )
                        sub_points = points[mask]
                        writers[i].write_points(sub_points)

                    point_piped += np.sum(mask)
                    if point_piped == len(points):
                        break
                count += len(points)
            logger.info(f"Progress: {count / file.header.point_count * 100}%")
        finally:
            for writer in writers:
                if writer is not None:
                    writer.close()


def main() -> None:
    """
    Command line interface for splitting LAS files.
    """
    parser = argparse.ArgumentParser(
        "LAS recursive splitter", description="Splits a las file bounds recursively"
    )
    parser.add_argument("input_file")
    parser.add_argument("output_dir")
    parser.add_argument("size", type=tuple_size, help="eg: 50x64.17")
    parser.add_argument("--points-per-iter", default=10**6, type=int)

    args = parser.parse_args()
    split_las_file(args.input_file, args.output_dir, args.size, args.points_per_iter)


if __name__ == "__main__":
    main()