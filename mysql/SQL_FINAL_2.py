import mysql.connector
from fpdf import FPDF
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import messagebox, simpledialog, Toplevel
import os
import threading
from queue import Queue
from ttkbootstrap import Style
from datetime import datetime

# Функция подключения к базе данных
def connect_to_db(user, password):
    try:
        cnx = mysql.connector.connect(
            user=user,
            password=password,
            host="localhost",
            database="kurs",
            use_unicode=True,
            charset="utf8"
        )
        return cnx
    except mysql.connector.Error as err:
        messagebox.showerror("Ошибка", f"Ошибка подключения к базе данных: {err}")
        return None

# Функция генерации статистики по серверам
def generate_server_statistics(cnx, order_by, error_queue):
    try:
        cursor = cnx.cursor()
        query = f"""
            SELECT 
                s.ID_Server,
                s.Adress,
                s.City,
                m.ModelName AS ServerModel,
                s.StorageLeft,
                s.MonthlyRentCost,
                e.Surname AS TechnicianSurname,
                e.Name AS TechnicianName
            FROM 
                servers s
            JOIN 
                models m ON s.Model_ID = m.ID_Model
            JOIN 
                employees e ON s.Technician_ID = e.ID_Employee
            ORDER BY s.ID_Server {order_by};
        """
        cursor.execute(query)
        data = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        cursor.close()  # Закрываем курсор после использования

        pdf = FPDF()
        pdf.add_page()
        pdf.add_font("DejaVuSans", "", "DejaVuSans.ttf", uni=True)
        pdf.set_font("DejaVuSans", size=12)
        pdf.cell(200, 10, txt="Статистика по серверам", ln=True, align='C')

        pdf.set_font("DejaVuSans", size=12)
        for col in columns:
            pdf.cell(40, 10, txt=col, border=1, align='C')
        pdf.ln(10)

        for row in data:
            for cell in row:
                pdf.cell(40, 10, txt=str(cell), border=1, align='C')
            pdf.ln(10)

        pdf.output("server_statistics.pdf")
        os.startfile("server_statistics.pdf")
    except Exception as e:
        error_queue.put(e)

# Функция генерации договора аренды
def generate_rental_contract(cnx, contract_id, error_queue):
    try:
        cursor = cnx.cursor()

        # Получение данных из базы данных
        query = f"""
            SELECT 
                c.ID_Contracts,
                ri.Surname AS RenterSurname,
                ri.Name AS RenterName,
                rl.Name AS RenterLegalName,
                c.RentedSpace,
                c.MonthlyPayments,
                c.StartDate,
                c.EndDate,
                c.RenterType,
                s.Adress AS ServerAdress,
                s.City AS ServerCity,
                e.Surname AS SellerSurname,
                e.Name AS SellerName,
                e.AccountNumber AS SellerAccountNumber
            FROM 
                contracts c
            LEFT JOIN 
                renterindividual ri ON c.Renter_ID = ri.ID_RenterIndividual AND c.RenterType = 'Individual'
            LEFT JOIN 
                renterlegal rl ON c.Renter_ID = rl.ID_RenterLegal AND c.RenterType = 'Legal'
            JOIN 
                servers s ON c.Server_ID = s.ID_Server
            JOIN 
                employees e ON c.Seller_ID = e.ID_Employee
            WHERE c.ID_Contracts = {contract_id};
        """
        cursor.execute(query)
        data = cursor.fetchone()
        cursor.close()  # Закрываем курсор после использования

        if data is None:
            error_queue.put("No contract data found.")
            return

        # Определение типа арендатора и соответствующего шаблона
        if data[8] == 'Individual':
            template_file = 'contract_template_individual.txt'
            renter_surname = data[1]
            renter_name = data[2]
            renter_legal_name = ""
        elif data[8] == 'Legal':
            template_file = 'contract_template_legal.txt'
            renter_surname = ""
            renter_name = ""
            renter_legal_name = data[3]

        # Чтение шаблона договора из файла
        with open(template_file, 'r', encoding='utf-8') as file:
            contract_template = file.read()

        # Подставляем данные в шаблон
        monthly_payment = data[5]
        start_date = data[6]
        end_date = data[7]
        seller_surname = data[12]
        seller_name = data[11]
        email = "nikita.buharinov@mail.ru"

        filled_contract = contract_template.format(
            renter_surname=renter_surname,
            renter_name=renter_name,
            renter_legal_name=renter_legal_name,
            monthly_payment=monthly_payment,
            start_date=start_date,
            end_date=end_date,
            seller_surname=seller_surname,
            seller_name=seller_name,
            email=email
        )

        # Кодировка текста перед записью в PDF
        encoded_text = filled_contract.encode('utf-8', errors='ignore').decode('utf-8')

        # Создание PDF-документа
        pdf = FPDF()
        pdf.add_page()
        pdf.add_font("DejaVuSans", "", "DejaVuSans.ttf", uni=True)
        pdf.set_font("DejaVuSans", size=10)

        for line in encoded_text.split('\n'):
            pdf.multi_cell(0, 5,
                           txt=line)

        pdf.output("rental_contract.pdf")
        os.startfile("rental_contract.pdf")
    except Exception as e:
        error_queue.put(e)

# Функция генерации прибыли по месяцам с гистограммой (главный поток)
def generate_profit_by_month_main(cnx, start_date, end_date, error_queue):
    try:
        cursor = cnx.cursor()
        query = f"""
            SELECT 
                YEAR(p.PaymentDate) AS Year,
                MONTH(p.PaymentDate) AS Month,
                SUM(p.PaymentAmount) AS TotalPayment
            FROM 
                payments p
            WHERE p.PaymentDate BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY 
                YEAR(p.PaymentDate), MONTH(p.PaymentDate)
            ORDER BY 
                Year, Month;
        """
        cursor.execute(query)
        data = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        cursor.close()

        if not data:
            error_queue.put("No payment data found.")
            return

        # Данные для графика
        months = [f"{row[0]}-{row[1]:02d}" for row in data]
        payments = [row[2] for row in data]

        # Создание графика в главном потоке
        plt.figure(figsize=(10, 5))
        plt.bar(months, payments)
        plt.xlabel('Месяц')
        plt.ylabel('Общая сумма платежей')
        plt.title('Прибыль по месяцам')
        plt.xticks(rotation=90)
        plt.tight_layout()

        # Сохранение графика как файл
        plt.savefig('profit_by_month_graph.png', dpi=300)

        # Создание PDF-документа
        pdf = FPDF()

        # Добавление первой страницы для графика
        pdf.add_page()

        # Включение графика в PDF-документ
        pdf.image('profit_by_month_graph.png', x=10, y=50, w=190)

        # Добавление второй страницы для таблицы
        pdf.add_page()

        # Заголовок таблицы
        pdf.add_font("DejaVuSans", "", "DejaVuSans.ttf", uni=True)
        pdf.set_font("DejaVuSans", size=12)

        # Заголовки таблицы
        pdf.cell(40, 10, txt="Год-Месяц", border=1, align='C')
        pdf.cell(60, 10, txt="Общая сумма платежей", border=1, align='C')

        # Переход на новую строку после заголовков
        pdf.ln(10)

        # Данные таблицы
        for i in range(len(data)):
            pdf.cell(40, 10, txt=f"{data[i][0]}-{data[i][1]:02d}", border=1, align='C')
            pdf.cell(60, 10, txt=str(data[i][2]), border=1, align='C')

            # Переход на новую строку после каждой строки данных
            pdf.ln(10)

        pdf.output("profit_by_month.pdf")
        os.startfile("profit_by_month.pdf")
    except Exception as e:
        error_queue.put(e)


def login_window():
    def login():
        global cnx, user_role  # Добавляем глобальную переменную user_role
        user = user_entry.get()
        password = password_entry.get()

        if not all([user, password]):
            messagebox.showerror("Ошибка", "Все поля должны быть заполнены.")
            return

        cnx = connect_to_db(user, password)

        if cnx is not None:
            user_role = user  # Сохраняем роль пользователя
            for widget in login_frame.winfo_children():
                widget.destroy()
            login_frame.pack_forget()
            document_frame.pack(fill=tk.BOTH, expand=True)

    global login_frame
    style = Style(theme="superhero")
    root = style.master

    root.title("Авторизация")
    root.geometry("1024x768")

    login_frame = tk.Frame(root, bg="#F5F5DC")
    login_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    frame_login = tk.Frame(login_frame, bg="#F5F5DC")
    frame_login.pack(pady=20)

    tk.Label(frame_login, text="Пользователь", bg="#F5F5DC", font=("Arial", 16)).grid(row=0, column=0, padx=10, pady=10)
    tk.Label(frame_login, text="Пароль", bg="#F5F5DC", font=("Arial", 16)).grid(row=1, column=0, padx=10, pady=10)

    global user_entry
    user_entry = tk.Entry(frame_login, font=("Arial", 16))
    user_entry.grid(row=0, column=1, padx=10, pady=10)

    global password_entry
    password_entry = tk.Entry(frame_login, show="*", font=("Arial", 16))
    password_entry.grid(row=1, column=1, padx=10, pady=10)

    tk.Button(frame_login, text="Подтвердить", command=login, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).grid(row=2, column=0, columnspan=2, padx=10, pady=20)


def show_documents():
    for widget in second_frame.winfo_children():
        widget.destroy()

    tk.Button(second_frame, text="Статистика по серверам", command=get_server_stats_order, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(pady=20)
    tk.Button(second_frame, text="Договор аренды", command=get_contract_id, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(pady=20)
    tk.Button(second_frame, text="Прибыль по месяцам", command=get_dates, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(pady=20)


def get_server_stats_order():
    def get_order_by():
        order_by_window = Toplevel(root)
        order_by_window.title("Выбор порядка сортировки")

        tk.Label(order_by_window, text="Выберите порядок сортировки:", font=("Arial", 24)).pack(pady=40)
        tk.Button(order_by_window, text="По возрастанию", command=lambda: [order_by_window.destroy(),
                                                                           threading.Thread(
                                                                               target=generate_server_statistics,
                                                                               args=(cnx, 'ASC',
                                                                                     error_queue)).start()],
                   font=("Arial", 20)).pack(pady=20)
        tk.Button(order_by_window, text="По убыванию", command=lambda: [order_by_window.destroy(), threading.Thread(
            target=generate_server_statistics, args=(cnx, 'DESC', error_queue)).start()],
                   font=("Arial", 20)).pack(pady=20)

    get_order_by()


def get_contract_id():
    contract_id = simpledialog.askinteger("Введите ID договора аренды", "ID договора аренды")
    if contract_id is not None:
        threading.Thread(target=generate_rental_contract, args=(cnx, contract_id, error_queue)).start()


def get_dates():
    while True:
        start_date = simpledialog.askstring("Введите начальную дату", "Начальная дата (YYYY-MM-01)")
        end_date = simpledialog.askstring("Введите конечную дату", "Конечная дата (YYYY-MM-01)")

        # Проверка формата дат
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

            # Проверка того, что начальная дата не позднее конечной
            if start_date_obj > end_date_obj:
                messagebox.showerror("Ошибка", "Начальная дата должна быть раньше конечной.")
                continue

            generate_profit_by_month_main(cnx, start_date, end_date, error_queue)
            break
        except ValueError:
            messagebox.showerror("Ошибка", "Неправильный формат даты. Используйте YYYY-MM-01.")


def db_management_window():
    global error_queue

    def show_table_options(table_name):
        table_options_window = Toplevel(root)
        table_options_window.title(f"Операции с таблицей {table_name}")

        def view_table():
            view_table_window = Toplevel(table_options_window)
            view_table_window.title(f"Просмотр таблицы {table_name}")

            # Получение названий столбцов
            cursor = cnx.cursor()
            query = f"SELECT * FROM {table_name} LIMIT 1"
            cursor.execute(query)
            columns = [desc[0] for desc in cursor.description]
            cursor.fetchall()  # Прочитываем результаты запроса
            cursor.close()

            # Checkbox для каждого столбца
            checkboxes = []
            for col in columns:
                var = tk.IntVar()
                checkboxes.append(var)
                tk.Checkbutton(view_table_window, text=col, variable=var).pack(pady=10)

            # Поле для количества строк
            tk.Label(view_table_window, text="Количество строк").pack(pady=10)
            row_count_entry = tk.Entry(view_table_window)
            row_count_entry.pack(pady=10)

            def display_table():
                selected_columns = [columns[i] for i, var in enumerate(checkboxes) if var.get()]
                row_count = row_count_entry.get()

                if row_count:
                    query = f"SELECT {', '.join(selected_columns)} FROM {table_name} LIMIT {row_count}"
                else:
                    query = f"SELECT {', '.join(selected_columns)} FROM {table_name}"

                cursor = cnx.cursor()
                cursor.execute(query)
                data = cursor.fetchall()
                cursor.close()

                # Вывод таблицы
                result_window = Toplevel(view_table_window)
                result_window.title(f"Результат просмотра таблицы {table_name}")

                for i, col in enumerate(selected_columns):
                    tk.Label(result_window, text=col).grid(row=0, column=i, padx=10, pady=10)

                for i, row in enumerate(data):
                    for j, cell in enumerate(row):
                        tk.Label(result_window, text=str(cell)).grid(row=i+1, column=j, padx=10, pady=10)

            tk.Button(view_table_window, text="Показать таблицу", command=display_table).pack(pady=20)

        def edit_table():
            edit_table_window = Toplevel(table_options_window)
            edit_table_window.title(f"Корректировка таблицы {table_name}")

            # Получение названий столбцов
            cursor = cnx.cursor()
            query = f"SELECT * FROM {table_name} LIMIT 1"
            cursor.execute(query)
            columns = [desc[0] for desc in cursor.description]
            cursor.fetchall()  # Прочитываем результаты запроса
            cursor.close()

            # Поле для ID строки
            tk.Label(edit_table_window, text="ID строки").grid(row=0, column=0, padx=10, pady=10)
            id_entry = tk.Entry(edit_table_window)
            id_entry.grid(row=0, column=1, padx=10, pady=10)

            # Checkbox для каждого столбца и поля для ввода новых данных
            checkboxes = []
            new_data_entries = []
            for i, col in enumerate(columns):
                var = tk.IntVar()
                checkboxes.append(var)
                tk.Checkbutton(edit_table_window, text=col, variable=var).grid(row=i+1, column=0, padx=10, pady=5)
                entry = tk.Entry(edit_table_window)
                entry.grid(row=i+1, column=1, padx=10, pady=5)
                new_data_entries.append(entry)

            def update_table():
                selected_columns = [columns[i] for i, var in enumerate(checkboxes) if var.get()]
                new_data = [entry.get() for entry in new_data_entries]

                query = f"UPDATE {table_name} SET "
                query += ", ".join(f"{col} = %s" for col in selected_columns)
                query += f" WHERE ID = %s"

                cursor = cnx.cursor()
                cursor.execute(query, (*new_data[:len(selected_columns)], id_entry.get()))
                cnx.commit()
                cursor.close()

            tk.Button(edit_table_window, text="Обновить строку", command=update_table).grid(row=len(columns)+1, column=0, columnspan=2, padx=10, pady=20)
            tk.Button(edit_table_window, text="Просмотреть таблицу", command=view_table).grid(row=len(columns)+2, column=0, columnspan=2, padx=10, pady=10)

        def delete_table():
            delete_table_window = Toplevel(table_options_window)
            delete_table_window.title(f"Удаление из таблицы {table_name}")

            # Поле для ID строки
            tk.Label(delete_table_window, text="ID строки").grid(row=0, column=0, padx=10, pady=10)
            id_entry = tk.Entry(delete_table_window)
            id_entry.grid(row=0, column=1, padx=10, pady=10)

            def delete_row():
                query = f"DELETE FROM {table_name} WHERE ID = %s"
                cursor = cnx.cursor()
                cursor.execute(query, (id_entry.get(),))
                cnx.commit()
                cursor.fetchall()  # Прочитываем результаты запроса, если они есть
                cursor.close()

            tk.Button(delete_table_window, text="Удалить строку", command=delete_row).grid(row=1, column=0, columnspan=2, padx=10, pady=20)
            tk.Button(delete_table_window, text="Просмотреть таблицу", command=view_table).grid(row=2, column=0, columnspan=2, padx=10, pady=10)

        def add_to_table():
            add_to_table_window = Toplevel(table_options_window)
            add_to_table_window.title(f"Добавление в таблицу {table_name}")

            # Получение названий столбцов
            cursor = cnx.cursor()
            query = f"SELECT * FROM {table_name} LIMIT 1"
            cursor.execute(query)
            columns = [desc[0] for desc in cursor.description]
            cursor.fetchall()  # Прочитываем результаты запроса
            cursor.close()

            # Поля для ввода новых данных
            new_data_entries = []
            for i, col in enumerate(columns):
                tk.Label(add_to_table_window, text=f"Значение для {col}").grid(row=i, column=0, padx=10, pady=5)
                entry = tk.Entry(add_to_table_window)
                entry.grid(row=i, column=1, padx=10, pady=5)
                new_data_entries.append(entry)

            def insert_row():
                query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})"
                cursor = cnx.cursor()
                cursor.execute(query, (*[entry.get() for entry in new_data_entries],))
                cnx.commit()
                cursor.close()

            tk.Button(add_to_table_window, text="Добавить строку", command=insert_row).grid(row=len(columns), column=0, columnspan=2, padx=10, pady=20)
            tk.Button(add_to_table_window, text="Просмотреть таблицу", command=view_table).grid(row=len(columns)+1, column=0, columnspan=2, padx=10, pady=10)

        tk.Button(table_options_window, text="Просмотр", command=view_table).pack(pady=20)
        tk.Button(table_options_window, text="Корректировка", command=edit_table).pack(pady=20)
        tk.Button(table_options_window, text="Удаление", command=delete_table).pack(pady=20)
        tk.Button(table_options_window, text="Добавление", command=add_to_table).pack(pady=20)

    global user_role  # Используем сохраненную роль пользователя

    if user_role in ['root', 'administrator', 'manager']:
        available_tables = ['contracts', 'renterindividual', 'renterlegal', 'servers', 'employees', 'models',
                            'payments']
    elif user_role == 'seller':
        available_tables = ['contracts', 'renterindividual', 'renterlegal']
    else:
        available_tables = []

    for table in available_tables:
        tk.Button(db_management_frame, text=table, command=lambda t=table: show_table_options(t)).pack(pady=20)


# Добавление раздела "Ведение БД" в главное меню
def show_db_management():
    global db_management_frame, error_queue
    for widget in second_frame.winfo_children():
        widget.destroy()

    db_management_frame = tk.Frame(second_frame, bg="#F5F5DC", highlightbackground="black", highlightthickness=1)
    db_management_frame.pack(fill=tk.BOTH, expand=True)

    db_management_window()
    db_management_frame.update_idletasks()  # Обновляем фрейм после добавления кнопок



# Добавление кнопки "Ведение БД" в меню
global root
style = Style(theme="superhero")
root = style.master

root.title("Авторизация")
root.geometry("1024x768")

global login_frame
login_frame = tk.Frame(root, bg="#F5F5DC")
login_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

global document_frame
document_frame = tk.Frame(root, bg="#F5F5DC")
document_frame.pack_forget()

global first_frame
first_frame = tk.Frame(document_frame, bg="#F5F5DC", highlightbackground="black", highlightthickness=1)
first_frame.pack(side=tk.LEFT, fill=tk.Y)

global second_frame
second_frame = tk.Frame(document_frame, bg="#F5F5DC", highlightbackground="black", highlightthickness=1)
second_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

tk.Button(first_frame, text="Выходные документы", command=show_documents, bg="#FFFFFF", fg="#000000",
          font=("Arial", 16)).pack(pady=20)
tk.Button(first_frame, text="Ведение БД", command=show_db_management, bg="#FFFFFF", fg="#000000",
          font=("Arial", 16)).pack(pady=20)

error_queue = Queue()


def check_errors():
    while True:
        error = error_queue.get()
        if error:
            messagebox.showerror("Ошибка", str(error))


threading.Thread(target=check_errors).start()

login_window()

if __name__ == "__main__":
    root.mainloop()