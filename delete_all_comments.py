import re
import os
import asyncio
import argparse
import traceback
from colorama import Fore, Style

import aiovk
from aiovk.exceptions import VkAPIError

from bs4 import BeautifulSoup


class VkDeleter:
    api: aiovk.API

    def __init__(self, access_token, comments_path):
        self.comments_path: str = comments_path
        self.access_token: str = access_token
        self.success_count: int = 0
        self.all_count: int = 0

    def get_posts(self):
        posts = []
        for comment in os.listdir(self.comments_path):
            with open(f"{self.comments_path}/{comment}", "r", encoding="ISO-8859-1") as file:
                val = file.read()
                links = BeautifulSoup(val, "lxml").find_all("div", {"class": "item"})
                posts.extend([link.a["href"] for link in links])
        return posts

    def get_credentials(self):
        posts = self.get_posts()
        self.all_count = len(posts)
        join_posts = "".join(posts)
        walls = re.findall(r"wall([-]?\d*)", join_posts)
        replies = re.findall(r"reply=(\d*)", join_posts)
        return zip(walls, replies, posts)

    def log(self, message: str, color: int, count: int, err: Exception = None):
        print(f"{count}/{self.all_count}:{color} {message} {Style.RESET_ALL}")
        if err is not None:
            print(err)

    async def delete_comment(self, owner_id, comment_id, link, count):
        try:
            await self.api.wall.deleteComment(owner_id=owner_id, comment_id=comment_id, v="5.131")
            self.log(f"Успешно удалено {link}", Fore.GREEN, count)
            self.success_count += 1
        except VkAPIError as err:
            if err.error_code == 211 or err.error_code == 15:
                self.log(f"Комментарий уже удалён или нет доступа к записи {link}", Fore.YELLOW, count)
            elif err.error_code == 15:
                self.log(f"Доступ для удаления закрыт {link}", Fore.YELLOW, count)
            else:
                self.log(f"Неизвестная ошибка {link}", Fore.RED, count, err)
        except Exception as err:
            self.log(f"Неизвестная ошибка {link}", Fore.RED, count, err)

    async def run(self):
        async with aiovk.TokenSession(access_token=self.access_token) as ses:
            self.api = aiovk.API(ses)
            credentials = self.get_credentials()
            tasks = []
            count = 0
            for owner_id, comment_id, link in credentials:
                count += 1
                if len(tasks) == 3:
                    await asyncio.gather(*tasks)
                    del tasks[:]
                    await asyncio.sleep(1)
                tasks.append(asyncio.create_task(self.delete_comment(owner_id, comment_id, link, count)))
            await asyncio.gather(*tasks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Удаление всех комментариев из вк")
    parser.add_argument(
        "--token",
        help="Access token для vk api (как получить смотреть README.MD)",
        type=str,
    )
    parser.add_argument(
        "--path",
        help="Путь к выгруженным комментариям (как получить смотреть README.MD)",
        type=str,
    )
    args = parser.parse_args()
    processor = VkDeleter(comments_path=args.path, access_token=args.token)
    try:
        asyncio.run(processor.run())
    except KeyboardInterrupt:
        traceback.print_exc()
        print(f"Удалено {processor.success_count} комментариев из {processor.all_count}")
