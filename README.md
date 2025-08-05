# Python vk.com comment deleter
Удаляем все комментарии из vk.com

## Подготовка к выполнению
Нет технической возможности через API стянуть все ваши комментарии
автоматически, поэтому нужно их запросить при помощи: 
https://vk.com/data_protection?section=rules 

По запросу вам выдаст архив со всеми данными, которые вы запросили, после распаковки
которого у вас появится директория comments

Так же для работы вам понадобится ваш access token, его можно получить, самостоятельно зарегистрировав
приложения, либо перейти по ссылке: 
https://oauth.vk.com/authorize?client_id=6061680&display=page&scope=wall&response_type=token&v=5.131 и вас перенаправит
на другой URL адрес, в теле которого будет access token


## Установка и запуск
1. Для корректной работы необходимо наличие python 3.7.x и выше, pip для интерпретатора
2. Устанавливаете зависимости проекта `pip3 install -r requirements.txt`
3. Запускаете `python3 delete_all_comments.py --token your_token --path path_to_comments_directory`
