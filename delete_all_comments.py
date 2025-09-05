import re
import os
import argparse
import asyncio
import sys
from typing import List, Dict, Tuple, Optional
from bs4 import BeautifulSoup
from aiovk import TokenSession, API
from colorama import Fore, init

init(autoreset=True)


class VkCommentDeleter:
    """Класс для удаления комментариев ВКонтакте с использованием DI"""
    
    def __init__(self, api: API):
        self.api = api
        self.semaphore = asyncio.Semaphore(3)  # Ограничение 3 RPS
        
    async def _parse_html_file(self, filepath: str) -> List[str]:
        """Парсит HTML файл и извлекает ссылки на комментарии"""
        try:
            with open(filepath, "r", encoding="windows-1251") as file:
                html_content = file.read()
        except UnicodeDecodeError:
            try:
                with open(filepath, "r", encoding="utf-8") as file:
                    html_content = file.read()
            except UnicodeDecodeError:
                try:
                    with open(filepath, "r", encoding="ISO-8859-1") as file:
                        html_content = file.read()
                except Exception as e:
                    print(f"{Fore.RED}❌ Ошибка чтения файла {filepath}: {e}")
                    return []
            except Exception as e:
                print(f"{Fore.RED}❌ Ошибка чтения файла {filepath}: {e}")
                return []
        
        soup = BeautifulSoup(html_content, "lxml")
        comment_links = []
        
        for a in soup.select("div.item div.item__main a"):
            href = a.get('href', '')
            if 'wall' in href and 'reply=' in href:
                comment_links.append(href)
                
        return comment_links

    def _parse_comment_links(self, links: List[str]) -> List[Dict]:
        """Парсит ссылки на комментарии и извлекает идентификаторы"""
        parsed_data = []
        
        for link in links:
            wall_match = re.search(r"wall(-?\d+)_(\d+)", link)
            if not wall_match:
                continue
                
            owner_id = int(wall_match.group(1))
            post_id = int(wall_match.group(2))

            reply_match = re.search(r"reply=(\d+)", link)
            if not reply_match:
                continue
                
            comment_id = int(reply_match.group(1))

            parsed_data.append({
                "link": link,
                "owner_id": owner_id,
                "post_id": post_id,
                "comment_id": comment_id,
            })
            
        return parsed_data

    async def _delete_comment_with_retry(self, comment: Dict, index: int, total: int) -> bool:
        """Удаляет комментарий с повторными попытками при ошибках"""
        max_retries = 3
        retry_delay = 2.0
        
        def is_retryable_error(error_msg: str) -> bool:
            retryable_errors = [
                "Too many requests per second",
                "Internal server error",
                "Service temporarily unavailable",
                "Connection error"
            ]
            return any(err in error_msg for err in retryable_errors)
        
        for attempt in range(max_retries + 1):
            try:
                async with self.semaphore:
                    result = await self.api.wall.deleteComment(
                        owner_id=comment['owner_id'],
                        comment_id=comment['comment_id']
                    )
                
                if result == 1:
                    print(f"{Fore.GREEN}✅ [{index}/{total}] Удален комментарий {comment['comment_id']}")
                    return True
                else:
                    print(f"{Fore.RED}❌ [{index}/{total}] Не удалось удалить комментарий {comment['comment_id']}")
                    return False
                    
            except Exception as e:
                error_msg = str(e)
                
                if "Access denied" in error_msg or "wall's comment denied" in error_msg:
                    print(f"{Fore.RED}❌ [{index}/{total}] Нет доступа к комментарию {comment['comment_id']}")
                    return False
                elif "Comment not found" in error_msg:
                    print(f"{Fore.YELLOW}⚠️  [{index}/{total}] Комментарий {comment['comment_id']} уже удален")
                    return True
                elif "This profile is private" in error_msg:
                    print(f"{Fore.RED}❌ [{index}/{total}] Приватный профиль - комментарий {comment['comment_id']}")
                    return False
                
                elif is_retryable_error(error_msg) and attempt < max_retries:
                    wait_time = retry_delay * (attempt + 1)
                    print(f"{Fore.YELLOW}⏳ [{index}/{total}] Попытка {attempt + 1}/{max_retries} неудачна для {comment['comment_id']}, ждем {wait_time}с...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    print(f"{Fore.RED}❌ [{index}/{total}] Окончательная ошибка для {comment['comment_id']}: {error_msg}")
                    return False
        
        return False

    async def delete_comments(self, comments_path: str, auto_confirm: bool = False) -> Tuple[int, int, int]:
        """Удаляет все комментарии используя VK API"""
        print(f"{Fore.CYAN}🔍 Анализируем комментарии в папке: {comments_path}")
        
        all_links = []
        files_count = 0
        
        for filename in os.listdir(comments_path):
            filepath = os.path.join(comments_path, filename)
            if not os.path.isfile(filepath) or not filename.endswith('.html'):
                continue
                
            files_count += 1
            print(f"{Fore.YELLOW}📄 Обрабатываем файл: {filename}")
            
            links = await self._parse_html_file(filepath)
            all_links.extend(links)
            print(f"  Найдено комментариев: {len(links)}")

        parsed_data = self._parse_comment_links(all_links)
        total_comments = len(parsed_data)
        
        print(f"\n{Fore.CYAN}{'-'*60}")
        print("📊 СТАТИСТИКА:")
        print(f"Обработано файлов: {files_count}")
        print(f"Всего найдено комментариев: {total_comments}")
        print(f"{'-'*60}")

        if total_comments == 0:
            print(f"{Fore.YELLOW}⚠️  Комментарии для удаления не найдены")
            return 0, 0, 0

        print(f"\n{Fore.RED}⚠️  ВНИМАНИЕ! Вы собираетесь удалить {total_comments} комментариев.")
        print(f"{Fore.RED}Это действие необратимо!")
        
        if not auto_confirm:
            confirmation = input(f"\n{Fore.YELLOW}Продолжить? (yes/no): ").lower().strip()
            if confirmation not in ['yes', 'y', 'да']:
                print(f"{Fore.CYAN}❌ Операция отменена пользователем")
                return 0, 0, 0
        else:
            print(f"\n{Fore.GREEN}🤖 Автоматическое подтверждение активировано - продолжаем удаление")

        print(f"\n{Fore.GREEN}🚀 Начинаем удаление комментариев с автоматическими повторными попытками...")
        
        deleted_count = 0
        permanently_failed = []
        
        # Основной цикл удаления
        for i, comment in enumerate(parsed_data, 1):
            success = await self._delete_comment_with_retry(comment, i, total_comments)
            if success:
                deleted_count += 1
            else:
                permanently_failed.append(comment)
        
        failed_count = len(permanently_failed)

        print(f"\n{Fore.CYAN}{'-'*60}")
        print("📊 РЕЗУЛЬТАТ:")
        print(f"{Fore.GREEN}✅ Успешно удалено: {deleted_count}")
        print(f"{Fore.RED}❌ Не удалось удалить: {failed_count}")
        print(f"📈 Процент успеха: {(deleted_count/total_comments)*100:.1f}%")
        
        # Показываем детали неудачных комментариев
        if permanently_failed:
            print(f"\n{Fore.YELLOW}📋 АНАЛИЗ НЕУДАЧНЫХ УДАЛЕНИЙ:")
            
            # Подсчитываем типы ошибок для отчета
            print(f"{Fore.YELLOW}💾 Сохранено {len(permanently_failed)} неудачных ссылок для дальнейшего анализа")
            print("   - Примеры неудачных ссылок:")
            for i, failed in enumerate(permanently_failed[:5]):  # Показываем первые 5
                print(f"     {i+1}. {failed['link']}")
            if len(permanently_failed) > 5:
                print(f"     ... и еще {len(permanently_failed) - 5} ссылок")
    
        print(f"\n{Fore.GREEN}🎯 ИТОГОВАЯ СТАТИСТИКА:")
        print(f"   Обработано файлов: {files_count}")
        print(f"   Найдено комментариев: {total_comments}")
        print(f"   Успешно удалено: {deleted_count}")
        print(f"   Не удалось удалить: {failed_count}")
        print(f"   Итоговый процент успеха: {(deleted_count/total_comments)*100:.1f}%")
        print(f"{'-'*60}")
        
        return deleted_count, failed_count, total_comments


async def run_multiple_iterations(
    deleter: VkCommentDeleter, 
    comments_path: str, 
    max_iterations: int, 
    auto_confirm: bool
) -> None:
    """Запускает несколько итераций удаления комментариев"""
    print(f"\n{Fore.CYAN}🔄 Режим множественных итераций активирован (макс. {max_iterations} итераций)")
    print(f"🤖 Автоподтверждение: {'включено' if auto_confirm else 'отключено'}")
    
    total_deleted_all_iterations = 0
    total_comments = 0
    iteration = 1
    
    while iteration <= max_iterations:
        print(f"\n{Fore.MAGENTA}{'='*70}")
        print(f"🔄 ИТЕРАЦИЯ {iteration}/{max_iterations}")
        print(f"{'='*70}")
        
        # Для первой итерации спрашиваем подтверждение, для остальных - автоматически
        auto_confirm_current = auto_confirm or (iteration > 1)
        
        deleted, failed, total = await deleter.delete_comments(
            comments_path, 
            auto_confirm=auto_confirm_current
        )
        
        total_deleted_all_iterations += deleted
        total_comments = total
        
        print(f"\n{Fore.CYAN}📊 РЕЗУЛЬТАТ ИТЕРАЦИИ {iteration}:")
        print(f"   Удалено в этой итерации: {deleted}")
        print(f"   Не удалось в этой итерации: {failed}")
        print(f"   Общий прогресс: {total_deleted_all_iterations}/{total_comments} ({(total_deleted_all_iterations/total_comments)*100:.1f}%)")
        
        if deleted < 5:
            print(f"\n{Fore.GREEN}✅ Достигнут порог стабилизации (удалено < 5 комментариев)")
            print("🏁 Завершаем итерации досрочно")
            break
            
        if iteration < max_iterations:
            print(f"\n{Fore.YELLOW}⏳ Пауза перед следующей итерацией (30 секунд)...")
            await asyncio.sleep(30)
        
        iteration += 1
    
    print(f"\n{Fore.GREEN}{'🎉'*70}")
    print("🏆 ФИНАЛЬНЫЙ РЕЗУЛЬТАТ ВСЕХ ИТЕРАЦИЙ:")
    print(f"   Выполнено итераций: {iteration if iteration <= max_iterations else max_iterations}")
    print(f"   Общее количество комментариев: {total_comments}")
    print(f"   Всего удалено: {total_deleted_all_iterations}")
    print(f"   Остается неудаленных: {total_comments - total_deleted_all_iterations}")
    print(f"   Итоговый процент успеха: {(total_deleted_all_iterations/total_comments)*100:.1f}%")
    print(f"{'🎉'*70}")


def main():
    parser = argparse.ArgumentParser(description="Удаление комментариев ВКонтакте")
    parser.add_argument(
        "--token",
        required=True,
        help="Access token ВКонтакте",
        type=str,
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Путь к папке с выгруженными комментариями",
        type=str,
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Максимальное количество итераций для повторных попыток (по умолчанию: 3)",
    )
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="Автоматически подтверждать удаление без запроса пользователя",
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.path):
        print(f"{Fore.RED}❌ Папка не найдена: {args.path}")
        sys.exit(1)
    
    if not os.path.isdir(args.path):
        print(f"{Fore.RED}❌ Указанный путь не является папкой: {args.path}")
        sys.exit(1)
    
    # Создаем сессию и API объект один раз
    session = TokenSession(access_token=args.token)
    session.API_VERSION = '5.131'
    api = API(session)
    
    # Создаем экземпляр класса для удаления комментариев
    deleter = VkCommentDeleter(api)
    
    try:
        asyncio.run(run_multiple_iterations(
            deleter, 
            args.path, 
            args.max_iterations, 
            args.auto_confirm
        ))
        
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}⚠️  Операция прервана пользователем")
    except Exception as e:
        print(f"\n{Fore.RED}❌ Критическая ошибка: {e}")
        sys.exit(1)
    finally:
        try:
            session.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()